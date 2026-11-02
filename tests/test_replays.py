from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena_api import store
from arena_api.app import app
from arena_api.replays import ReplayError, parse_replay

type Event = dict[str, Any]


def turn(n: int, events: list[Event]) -> dict[str, Any]:
    return {"turn": n, "events": events}


def block_turn(n: int, attacker: str, defender: str) -> dict[str, Any]:
    return turn(
        n,
        [
            {"t": 0, "type": "attack_start", "actor": attacker},
            {
                "t": 900,
                "type": "attack_verified",
                "actor": attacker,
                "problem": "6 * 7?",
                "answer": "42",
            },
            {"t": 900, "type": "defend_start", "actor": defender},
            {"t": 2100, "type": "defend_result", "actor": defender, "score": 1.0, "answer": "42"},
            {"t": 2100, "type": "block", "actor": defender},
            {"t": 2100, "type": "hp", "a": 100.0, "b": 100.0},
        ],
    )


def hit_turn(n: int, attacker: str, defender: str) -> dict[str, Any]:
    return turn(
        n,
        [
            {"t": 0, "type": "attack_start", "actor": attacker},
            {
                "t": 800,
                "type": "attack_verified",
                "actor": attacker,
                "problem": "hard?",
                "answer": "7",
            },
            {"t": 800, "type": "defend_start", "actor": defender},
            {"t": 3000, "type": "defend_result", "actor": defender, "score": 0.0, "answer": "8"},
            {"t": 3000, "type": "hit", "target": defender, "damage": 20.0},
            {"t": 3000, "type": "hp", "a": 100.0, "b": 80.0},
        ],
    )


def backfire_turn(n: int, attacker: str, *, retried: bool) -> dict[str, Any]:
    events: list[Event] = [{"t": 0, "type": "attack_start", "actor": attacker}]
    reason = "mismatch: snippet printed '2/3', stated '5/4'"
    if retried:
        events.append({"t": 4000, "type": "attack_retry", "actor": attacker, "reason": reason})
    events += [
        {"t": 7000, "type": "backfire", "actor": attacker, "reason": reason},
        {"t": 7000, "type": "hit", "target": attacker, "damage": 10.0},
        {"t": 7000, "type": "hp", "a": 90.0, "b": 80.0},
    ]
    return turn(n, events)


FIGHTERS = {
    "a": {"name": "alice", "provider": "groq", "model": "model-a", "persona": "You are bold."},
    "b": {"name": "bob", "provider": "gemini", "model": "model-b", "persona": "You are careful."},
}


def write_log(
    name: str,
    turns: list[dict[str, Any]],
    fighters: dict[str, dict[str, str]] | None = None,
) -> None:
    turns[-1]["events"].append(
        {"t": 1, "type": "match_end", "winner": "b", "reason": "decision", "turns": len(turns)}
    )
    log: dict[str, Any] = {"match_id": name, "turns": turns}
    if fighters:  # schema 2 (D-030); older logs have neither key
        log |= {"schema": 2, "fighters": fighters}
    store.insert_finished(name, log, parse_replay(name, log).summary)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_lists_replays_with_their_result(database: str, client: TestClient) -> None:
    write_log("m_b", [block_turn(1, "a", "b"), hit_turn(2, "b", "a")])
    write_log("m_a", [hit_turn(1, "a", "b")])

    response = client.get("/replays")

    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == ["m_a", "m_b"]
    assert response.json()[1] == {
        "id": "m_b",
        "winner": "b",
        "reason": "decision",
        "hp_a": 100.0,
        "hp_b": 80.0,
        "turn_count": 2,
        "name_a": None,
        "name_b": None,
    }


def test_replay_turns_carry_what_the_reveal_panel_shows(database: str, client: TestClient) -> None:
    write_log("m1", [hit_turn(1, "a", "b"), block_turn(2, "b", "a")])

    turns = client.get("/replays/m1").json()["turns"]

    assert turns[0] == {
        "n": 1, "attacker": "a", "outcome": "hit", "target": "b", "damage": 20.0,
        "damage_math": "20 × 1 × (1 − 0) = 20", "problem": "hard?", "stated_answer": "7",
        "defender_answer": "8", "score": 0.0, "timed_out": False, "retried": False,
        "failure_reason": None, "hp_a": 100.0, "hp_b": 80.0, "duration_ms": 3000,
        "code": None, "first_attempt": None,
    }  # fmt: skip
    assert (turns[1]["outcome"], turns[1]["damage"], turns[1]["damage_math"]) == (
        "block", 0.0, "no damage",
    )  # fmt: skip


@pytest.mark.parametrize("retried", [False, True])
def test_backfire_turn_shows_the_reason_and_whether_it_was_retried(
    database: str, client: TestClient, retried: bool
) -> None:
    write_log("m1", [backfire_turn(1, "a", retried=retried)])

    (shown,) = client.get("/replays/m1").json()["turns"]

    assert (shown["outcome"], shown["target"], shown["retried"]) == ("backfire", "a", retried)
    assert shown["failure_reason"] == "mismatch: snippet printed '2/3', stated '5/4'"
    assert shown["problem"] is None
    assert shown["damage_math"] == "20 × 1 × 0.5 = 10"


def test_defender_timeout_is_flagged(database: str, client: TestClient) -> None:
    timed_out = hit_turn(1, "a", "b")
    timed_out["events"][3] = {"t": 3000, "type": "timeout", "actor": "b"}
    write_log("m1", [timed_out])

    (shown,) = client.get("/replays/m1").json()["turns"]

    assert (shown["timed_out"], shown["score"], shown["defender_answer"]) == (True, None, None)
    assert shown["damage_math"] == "20 × 1 × (1 − 0) = 20"


def test_unknown_replay_is_404(database: str, client: TestClient) -> None:
    assert client.get("/replays/nope").status_code == 404


@pytest.mark.parametrize("bad_id", ["..%2Fsecret", "a.b", "a%20b"])
def test_ids_that_are_not_plain_names_are_404(
    database: str, client: TestClient, bad_id: str
) -> None:
    assert client.get(f"/replays/{bad_id}").status_code == 404


def test_a_stored_log_that_cannot_be_read_is_a_500(database: str, client: TestClient) -> None:
    write_log("m1", [block_turn(1, "a", "b")])
    with store.connect() as conn:
        conn.execute("UPDATE matches SET log = '{}'::jsonb WHERE id = 'm1'")

    assert client.get("/replays/m1").status_code == 500


def test_parsing_a_log_without_turns_is_an_error() -> None:
    with pytest.raises(ReplayError, match="m1"):
        parse_replay("m1", {"turns": []})


def attempt_fields(problem: str, answer: str) -> dict[str, str]:
    return {"problem": problem, "answer": answer, "code": f"print({answer})"}


def test_schema_2_log_names_the_fighters_and_reveals_their_personas(
    database: str, client: TestClient
) -> None:
    write_log("m1", [block_turn(1, "a", "b")], FIGHTERS)

    (summary,) = client.get("/replays").json()
    replay = client.get("/replays/m1").json()

    assert (summary["name_a"], summary["name_b"]) == ("alice", "bob")
    assert replay["fighter_a"] == FIGHTERS["a"]
    assert replay["fighter_b"]["persona"] == "You are careful."


def test_old_logs_without_a_header_have_no_fighters(database: str, client: TestClient) -> None:
    write_log("m1", [block_turn(1, "a", "b")])

    replay = client.get("/replays/m1").json()

    assert (replay["fighter_a"], replay["fighter_b"]) == (None, None)


def test_verified_turn_shows_the_attackers_code(database: str, client: TestClient) -> None:
    verified = block_turn(1, "a", "b")
    verified["events"][1]["code"] = "print(42)"
    write_log("m1", [verified], FIGHTERS)

    (shown,) = client.get("/replays/m1").json()["turns"]

    assert (shown["code"], shown["first_attempt"]) == ("print(42)", None)


def test_backfired_turn_shows_the_final_attempt_and_the_first_one(
    database: str, client: TestClient
) -> None:
    failed = backfire_turn(1, "a", retried=True)
    failed["events"][1] |= attempt_fields("first try", "41")
    failed["events"][2] |= attempt_fields("second try", "40")
    write_log("m1", [failed], FIGHTERS)

    (shown,) = client.get("/replays/m1").json()["turns"]

    assert (shown["problem"], shown["stated_answer"], shown["code"]) == (
        "second try", "40", "print(40)",
    )  # fmt: skip
    assert shown["first_attempt"] == {
        "problem": "first try",
        "answer": "41",
        "code": "print(41)",
        "reason": "mismatch: snippet printed '2/3', stated '5/4'",
    }


def test_replay_carries_the_starting_hp_for_the_health_bars(
    database: str, client: TestClient
) -> None:
    write_log("m1", [block_turn(1, "a", "b")])

    assert client.get("/replays/m1").json()["max_hp"] == 100.0
