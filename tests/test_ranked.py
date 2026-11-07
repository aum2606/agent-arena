import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import FIGHTER, SignIn, StubQueue, make_fighter

from arena.config import load_config
from arena.llm import Completion, LlmError
from arena.models import Fighter
from arena.prompts import ATTACK_REQUEST
from arena_api import fighters, store
from arena_api.app import app
from arena_api.db import fighters_config_path
from arena_api.jobs import play_match
from arena_api.ratings import K_FACTOR, START_RATING
from arena_api.replays import parse_replay

BOB_KEY = "gsk_test_bob_key_0000"

type Complete = Callable[[Fighter, str, str, int], Completion]


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """Ranked tests need the provider config, a key secret and a stand-in queue."""


def verified(client: TestClient, **changes: object) -> int:
    """A fighter whose latest version has passed a spar, the entry ticket to ranked."""
    fighter_id = make_fighter(client, **changes)
    fighters.mark_verified(fighter_id, 1)
    return fighter_id


def ranked(client: TestClient, fighter_id: int) -> Any:
    return client.post(f"/fighters/{fighter_id}/ranked")


def set_rating(fighter_id: int, rating: float, games: int = 0) -> None:
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO ratings (fighter_id, rating, games) VALUES (%s, %s, %s) "
            "ON CONFLICT (fighter_id) DO UPDATE SET rating = %s, games = %s",
            (fighter_id, rating, games, rating, games),
        )


def a_wins(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
    """Bob's snippet never matches his stated answer, so every attack of his backfires."""
    if user.endswith(ATTACK_REQUEST):
        code = "print(41)" if fighter.name == "bob/rex" else "print(42)"
        text = f"<problem>6 * 7?</problem><answer>42</answer><code>{code}</code>"
        return Completion(text, False)
    return Completion("<answer>42</answer>", False)


def all_blocked(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
    if user.endswith(ATTACK_REQUEST):
        text = "<problem>6 * 7?</problem><answer>42</answer><code>print(42)</code>"
        return Completion(text, False)
    return Completion("<answer>42</answer>", False)


def play(match_id: str, complete: Complete, keys_seen: list[dict[str, str]] | None = None) -> None:
    def complete_with(keys: dict[str, str]) -> Complete:
        if keys_seen is not None:
            keys_seen.append(dict(keys))
        return complete

    config = load_config(fighters_config_path())
    asyncio.run(play_match({"config": config, "complete_with": complete_with}, match_id))


def finished_match(sign_in: SignIn, complete: Complete = a_wins) -> str:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada)
    verified(bob, api_key=BOB_KEY)
    match_id = str(ranked(ada, ada_id).json()["id"])
    play(match_id, complete)
    return match_id


def test_ranked_pairs_the_fighter_with_another_owners_and_queues_the_match(
    sign_in: SignIn, queue: StubQueue
) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id, bob_id = verified(ada), verified(bob)

    response = ranked(ada, ada_id)

    assert response.status_code == 202
    body = response.json()
    assert (body["status"], body["fighter_a"], body["fighter_b"]) == (
        "queued",
        "ada/rex",
        "bob/rex",
    )
    row = store.get_match(body["id"])
    assert row is not None
    assert (row.mode, row.fighter_id, row.fighter_version) == ("ranked", ada_id, 1)
    assert (row.opponent_id, row.opponent_version) == (bob_id, 1)
    assert queue.jobs == [("play_match", (body["id"],))]


def test_a_fighter_must_have_sparred_before_it_can_enter_ranked(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = make_fighter(ada)
    verified(bob)

    response = ranked(ada, ada_id)

    assert response.status_code == 409
    assert "spar" in response.json()["detail"]


def test_an_unverified_opponent_is_not_paired(sign_in: SignIn, queue: StubQueue) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada)
    make_fighter(bob)

    assert ranked(ada, ada_id).status_code == 409
    assert queue.jobs == []


def test_fighters_of_the_same_owner_are_never_paired(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    ada_id = verified(ada)
    verified(ada, name="second")

    assert ranked(ada, ada_id).status_code == 409


def test_the_closest_rating_is_paired(sign_in: SignIn) -> None:
    ada, bob, cy = sign_in("ada"), sign_in("bob"), sign_in("cy")
    ada_id = verified(ada)
    set_rating(verified(bob), 1500)
    set_rating(verified(cy), 1250)

    assert ranked(ada, ada_id).json()["fighter_b"] == "cy/rex"


def test_an_opponent_at_its_daily_cap_is_skipped(sign_in: SignIn) -> None:
    ada, bob, cy = sign_in("ada"), sign_in("bob"), sign_in("cy")
    ada_id = verified(ada)
    bob_id = verified(bob, daily_match_cap=1)
    verified(cy)
    set_rating(ada_id, 1250)
    set_rating(bob_id, 1250)  # bob's fighter is the closest, until it is full

    assert [ranked(ada, ada_id).json()["fighter_b"] for _ in range(2)] == ["bob/rex", "cy/rex"]


def test_a_fighter_stops_at_its_own_daily_cap(sign_in: SignIn, queue: StubQueue) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada, daily_match_cap=1)
    verified(bob)

    assert ranked(ada, ada_id).status_code == 202
    assert ranked(ada, ada_id).status_code == 429
    assert len(queue.jobs) == 1


def test_only_the_owner_can_enter_a_fighter(sign_in: SignIn, queue: StubQueue) -> None:
    ada_id = verified(sign_in("ada"))
    verified(sign_in("bob"))

    assert ranked(sign_in("bob"), ada_id).status_code == 404
    assert ranked(TestClient(app), ada_id).status_code == 401
    assert queue.jobs == []


def test_a_played_match_rates_both_fighters_and_shows_the_owner_their_change(
    sign_in: SignIn,
) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id, bob_id = verified(ada), verified(bob, api_key=BOB_KEY)
    match_id = ranked(ada, ada_id).json()["id"]
    keys: list[dict[str, str]] = []

    play(match_id, a_wins, keys)

    assert keys == [{"ada/rex": FIGHTER["api_key"], "bob/rex": BOB_KEY}]
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM ratings ORDER BY fighter_id").fetchall()
    assert [(r["fighter_id"], r["rating"], r["games"]) for r in rows] == [
        (ada_id, START_RATING + K_FACTOR / 2, 1),
        (bob_id, START_RATING - K_FACTOR / 2, 1),
    ]
    assert [(r["wins"], r["draws"], r["losses"]) for r in rows] == [(1, 0, 0), (0, 0, 1)]
    status = ada.get(f"/matches/{match_id}").json()
    assert (status["status"], status["rating_delta"]) == ("finished", K_FACTOR / 2)


def test_a_draw_between_equals_changes_no_rating_but_counts_the_game(sign_in: SignIn) -> None:
    finished_match(sign_in, all_blocked)

    with store.connect() as conn:
        rows = conn.execute("SELECT rating, games, draws FROM ratings").fetchall()
    assert [(r["rating"], r["games"], r["draws"]) for r in rows] == [(START_RATING, 1, 1)] * 2


def test_a_failed_match_changes_no_rating(sign_in: SignIn) -> None:
    def broken(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        raise LlmError("groq rate limited after 8 retries")

    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada)
    verified(bob)
    match_id = ranked(ada, ada_id).json()["id"]

    play(match_id, broken)

    row = store.get_match(match_id)
    assert row is not None and row.status == "failed"
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM ratings").fetchone() == {"n": 0}


def test_a_match_is_rated_only_once(sign_in: SignIn) -> None:
    match_id = finished_match(sign_in)
    log = store.get_log(match_id)
    assert log is not None

    assert not store.finish_ranked(match_id, log, parse_replay(match_id, log).summary)

    with store.connect() as conn:
        games = [r["games"] for r in conn.execute("SELECT games FROM ratings").fetchall()]
    assert games == [1, 1]


def test_the_leaderboard_is_public_and_sorted_by_rating(sign_in: SignIn) -> None:
    finished_match(sign_in)

    response = TestClient(app).get("/leaderboard")

    assert response.status_code == 200
    first, second = response.json()
    assert (first["handle"], first["name"], first["rating"]) == ("ada", "rex", 1216.0)
    assert (first["games"], first["wins"], first["losses"], first["form"]) == (1, 1, 0, "W")
    assert (second["handle"], second["rating"], second["form"]) == ("bob", 1184.0, "L")
    assert "api_key" not in first and "persona" not in first


def test_a_ranked_replay_opens_only_for_the_two_owners(sign_in: SignIn) -> None:
    match_id = finished_match(sign_in)

    assert sign_in("ada").get(f"/replays/{match_id}").status_code == 200
    assert sign_in("bob").get(f"/replays/{match_id}").status_code == 200
    assert sign_in("cy").get(f"/replays/{match_id}").status_code == 404
    assert TestClient(app).get(f"/replays/{match_id}").status_code == 404
    assert store.list_finished() == []
