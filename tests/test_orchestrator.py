import random
from typing import Any

import pytest

from arena.battle_log import BattleLog
from arena.config import Settings
from arena.llm import Completion, LlmError, LlmTimeout
from arena.models import Fighter, MatchRecord
from arena.orchestrator import run_match
from arena.prompts import ATTACK_REQUEST, TOPICS
from arena.verifier import Verification

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    defender_max_tokens=128,
    snippet_timeout_s=5.0,
    call_delay_s=0.0,
    max_retries=0,
    backoff_base_s=0.0,
)
A = Fighter("alice", "p", "m", "persona a")
B = Fighter("bob", "p", "m", "persona b")

type Reply = str | Exception | Completion


def good_attack(
    answer: str = "42", code: str = "print(42)", problem: str = "What is the answer?"
) -> str:
    return f"<problem>{problem}</problem><answer>{answer}</answer><code>{code}</code>"


def answer(value: str) -> str:
    return f"<answer>{value}</answer>"


class FakeLlm:
    """Scripted fighters: each has a queue of attack replies and of defense replies."""

    def __init__(
        self,
        attacks: dict[str, list[Reply]] | None = None,
        defenses: dict[str, list[Reply]] | None = None,
    ) -> None:
        self.attacks = attacks or {}
        self.defenses = defenses or {}
        self.defense_calls = 0
        self.attack_requests: list[str] = []
        self.caps: list[tuple[str, int]] = []  # ("attack" or "defense", max_tokens)

    def __call__(self, fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        if user.endswith(ATTACK_REQUEST):
            self.caps.append(("attack", max_tokens))
            self.attack_requests.append(user)
            reply = self.attacks[fighter.name].pop(0)
        else:
            self.caps.append(("defense", max_tokens))
            self.defense_calls += 1
            reply = self.defenses[fighter.name].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, Completion) else Completion(reply, False)


def play(llm: FakeLlm) -> tuple[MatchRecord, BattleLog]:
    log = BattleLog("m1")
    return run_match(A, B, llm, SETTINGS, log, random.Random(0)), log


def event_types(log: BattleLog, turn: int) -> list[str]:
    return [e["type"] for e in log.to_dict()["turns"][turn - 1]["events"]]


def test_failed_defenses_hit_both_fighters_equally_and_roles_swap() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("0")] * 3, "bob": [answer("0")] * 3},
    )

    record, _ = play(llm)

    assert [t.attacker for t in record.turns] == ["a", "b", "a", "b", "a", "b"]
    assert all(t.outcome == "hit" for t in record.turns)
    assert [t.target for t in record.turns] == ["b", "a", "b", "a", "b", "a"]
    assert (record.hp_a, record.hp_b) == (40.0, 40.0)
    assert (record.result.winner, record.result.reason) == (None, "decision")
    assert (record.fighter_a, record.fighter_b) == ("alice", "bob")


def test_correct_answers_block_every_attack() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    record, _ = play(llm)

    assert all(t.outcome == "block" and t.damage == 0.0 for t in record.turns)
    assert (record.hp_a, record.hp_b) == (100.0, 100.0)


def test_symbolically_equal_answer_blocks() -> None:
    llm = FakeLlm(
        attacks={
            "alice": [good_attack("sqrt(8)", "print('sqrt(8)')")] * 3,
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("2*sqrt(2)")] * 3},
    )

    record, _ = play(llm)

    assert record.turns[0].outcome == "block"


def test_event_sequence_for_a_hit_and_for_a_block() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("0")] * 3},
    )

    _, log = play(llm)

    assert event_types(log, 1) == [
        "attack_start", "attack_verified", "defend_start", "defend_result", "hit", "hp",
    ]  # fmt: skip
    assert event_types(log, 2) == [
        "attack_start", "attack_verified", "defend_start", "defend_result", "block", "hp",
    ]  # fmt: skip
    hit = log.to_dict()["turns"][0]["events"][4]
    assert (hit["target"], hit["damage"]) == ("b", 20.0)
    assert log.to_dict()["turns"][0]["events"][5]["b"] == 80.0


def test_wrong_snippet_backfires_and_defender_is_never_asked() -> None:
    liar = good_attack(answer="42", code="print(41)")
    llm = FakeLlm(attacks={"alice": [liar] * 6, "bob": [liar] * 6})

    record, log = play(llm)

    assert llm.defense_calls == 0
    assert all(t.damage == 10.0 for t in record.turns)
    assert all(t.outcome == "backfire" and t.target == t.attacker for t in record.turns)
    assert event_types(log, 1) == ["attack_start", "attack_retry", "backfire", "hit", "hp"]
    backfire = log.to_dict()["turns"][0]["events"][2]
    assert backfire["actor"] == "a"
    assert "mismatch" in backfire["reason"]
    assert (record.hp_a, record.hp_b) == (70.0, 70.0)


@pytest.mark.parametrize("reply", ["no tags here", good_attack(code="raise SystemExit(1)")])
def test_malformed_or_crashing_attack_backfires(reply: str) -> None:
    llm = FakeLlm(
        attacks={
            "alice": [reply, reply, good_attack(), good_attack()],
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("0")] * 3, "bob": [answer("0")] * 3},
    )

    record, log = play(llm)

    assert record.turns[0].outcome == "backfire"
    assert record.turns[0].target == "a"
    assert "reason" in log.to_dict()["turns"][0]["events"][1]


def test_attacker_timeout_logs_timeout_then_backfires() -> None:
    llm = FakeLlm(
        attacks={
            "alice": [LlmTimeout("slow"), good_attack(), good_attack()],
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("0")] * 3, "bob": [answer("0")] * 3},
    )

    record, log = play(llm)

    assert event_types(log, 1) == ["attack_start", "timeout", "backfire", "hit", "hp"]
    assert record.turns[0].outcome == "backfire"


@pytest.mark.parametrize("reply", [LlmTimeout("slow"), Completion("<answer>42</answer>", True)])
def test_defender_timeout_or_truncation_is_a_timeout_and_a_hit(reply: Reply) -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"bob": [reply, answer("42"), answer("42")], "alice": [answer("42")] * 3},
    )

    record, log = play(llm)

    assert event_types(log, 1) == [
        "attack_start", "attack_verified", "defend_start", "timeout", "hit", "hp",
    ]  # fmt: skip
    assert record.turns[0].outcome == "hit"


def test_unparseable_defense_scores_zero() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"bob": ["I refuse"] + [answer("42")] * 2, "alice": [answer("42")] * 3},
    )

    record, log = play(llm)

    assert record.turns[0].outcome == "hit"
    result = log.to_dict()["turns"][0]["events"][3]
    assert (result["type"], result["score"]) == ("defend_result", 0.0)


def test_knockout_ends_the_match_early_and_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    # With Phase 0 numbers one fighter can take at most 90 damage in 6 turns (D-013), so raise
    # base damage to exercise the knockout path.
    monkeypatch.setattr("arena.orchestrator.BASE_DAMAGE", 40.0)
    liar = good_attack(code="print(41)")
    llm = FakeLlm(
        attacks={"alice": [liar] * 6, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("0")] * 3, "bob": [answer("42")] * 3},
    )

    record, log = play(llm)

    # alice: backfire -20 (turn 1), hit -40 (turn 2), backfire -20 (turn 3), hit -40 (turn 4) = KO.
    assert len(record.turns) == 4
    assert record.hp_a == 0.0
    assert (record.result.winner, record.result.reason) == ("b", "ko")
    assert event_types(log, 4)[-3:] == ["hp", "knockout", "match_end"]
    end = log.to_dict()["turns"][3]["events"][-1]
    assert (end["winner"], end["reason"]) == ("b", "ko")


def test_provider_failure_aborts_the_match() -> None:
    llm = FakeLlm(attacks={"alice": [LlmError("rate limited after 5 retries")]})

    with pytest.raises(LlmError, match="rate limited"):
        play(llm)


def test_attacker_prompts_list_the_problems_posed_so_far() -> None:
    llm = FakeLlm(
        attacks={
            "alice": [good_attack(problem=f"alice problem {i}") for i in range(3)],
            "bob": [good_attack(problem=f"bob problem {i}") for i in range(3)],
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    play(llm)

    first, second, third = llm.attack_requests[:3]
    assert "alice problem 0" not in first
    assert "alice problem 0" in second
    assert "alice problem 0" in third
    assert "bob problem 0" in third


def test_backfired_problems_are_not_listed_as_used() -> None:
    liar = good_attack(code="print(41)", problem="never verified")
    llm = FakeLlm(
        attacks={"alice": [liar] * 6, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    play(llm)

    assert all("- never verified" not in request for request in llm.attack_requests)


def test_each_turn_gets_a_topic_from_the_rng() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )
    rng = random.Random(0)
    expected = [rng.choice(TOPICS) for _ in range(6)]

    play(llm)

    assert len(llm.attack_requests) == 6
    for request, topic in zip(llm.attack_requests, expected, strict=True):
        assert topic in request


def test_run_match_uses_the_injected_verifier() -> None:
    seen: list[str] = []

    def verify(stated: str, snippet: str, timeout_s: float) -> Verification:
        seen.append(stated)
        return Verification(False, "injected failure")

    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 6, "bob": [good_attack()] * 6},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )
    log = BattleLog("m1")

    record = run_match(A, B, llm, SETTINGS, log, random.Random(0), verify)

    assert len(seen) == 12  # every attack is checked twice: the draft and its retry
    assert all(t.outcome == "backfire" for t in record.turns)
    assert llm.defense_calls == 0
    assert "injected failure" in str(log.to_dict())


def blocked_everything() -> FakeLlm:
    return FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )


def test_prior_outcomes_reach_the_attacker_prompt() -> None:
    llm = blocked_everything()
    history = {"a": ["block", "block", "hit"], "b": []}

    run_match(A, B, llm, SETTINGS, BattleLog("m1"), random.Random(0), history=history)

    first_a, first_b = llm.attack_requests[:2]
    assert "blocked by your opponent (too easy): 2" in first_a
    assert "hit your opponent: 1" in first_a
    assert "How your last" not in first_b


def test_this_matchs_outcomes_join_the_history_as_it_goes() -> None:
    llm = blocked_everything()

    play(llm)

    # alice attacks on turns 1, 3, 5 (requests 0, 2, 4); her turn-1 problem was blocked.
    turn3 = llm.attack_requests[2]
    assert "How your last 1 problems fared" in turn3
    assert "blocked by your opponent (too easy): 1" in turn3
    assert "How your last" not in llm.attack_requests[0]


def test_run_match_does_not_modify_the_callers_history() -> None:
    history: dict[str, list[str]] = {"a": ["hit"], "b": ["block"]}

    run_match(
        A, B, blocked_everything(), SETTINGS, BattleLog("m1"), random.Random(0), history=history
    )

    assert history == {"a": ["hit"], "b": ["block"]}


def test_defender_gets_its_own_token_cap() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    play(llm)

    assert set(llm.caps) == {("attack", 256), ("defense", 128)}


def test_a_failed_check_gets_one_retry_that_shows_the_real_output() -> None:
    llm = FakeLlm(
        attacks={
            "alice": [good_attack(answer="41")] + [good_attack()] * 3,
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    record, log = play(llm)

    assert event_types(log, 1)[:4] == [
        "attack_start", "attack_retry", "attack_verified", "defend_start",
    ]  # fmt: skip
    assert record.turns[0].outcome == "block"
    retry = log.to_dict()["turns"][0]["events"][1]
    assert (retry["actor"], "snippet printed '42', stated '41'" in retry["reason"]) == ("a", True)
    assert "snippet printed '42', stated '41'" in llm.attack_requests[1]
    assert "snippet printed" not in llm.attack_requests[0]


def test_a_second_failed_check_backfires_with_the_retry_reason() -> None:
    attempts = [good_attack(answer="41"), good_attack(answer="40")] * 3
    llm = FakeLlm(
        attacks={"alice": attempts, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3},
    )

    record, log = play(llm)

    assert event_types(log, 1) == ["attack_start", "attack_retry", "backfire", "hit", "hp"]
    assert record.turns[0].outcome == "backfire"
    assert "stated '40'" in log.to_dict()["turns"][0]["events"][2]["reason"]


def test_unparseable_replies_and_timeouts_get_no_retry() -> None:
    llm = FakeLlm(
        attacks={
            "alice": ["no tags here", good_attack(), good_attack()],
            "bob": [LlmTimeout("slow"), good_attack(), good_attack()],
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    _, log = play(llm)

    assert event_types(log, 1) == ["attack_start", "backfire", "hit", "hp"]
    assert event_types(log, 2) == ["attack_start", "timeout", "backfire", "hit", "hp"]


def test_a_timeout_on_the_retry_backfires() -> None:
    llm = FakeLlm(
        attacks={
            "alice": [good_attack(answer="41"), LlmTimeout("slow"), good_attack(), good_attack()],
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    _, log = play(llm)

    assert event_types(log, 1) == [
        "attack_start", "attack_retry", "timeout", "backfire", "hit", "hp",
    ]  # fmt: skip


def test_log_header_names_both_fighters_with_their_personas() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    _, log = play(llm)

    data = log.to_dict()
    assert data["schema"] == 2
    assert data["fighters"]["a"] == {
        "name": "alice", "provider": "p", "model": "m", "persona": "persona a",
    }  # fmt: skip
    assert data["fighters"]["b"]["name"] == "bob"


def test_verified_attack_logs_its_snippet() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    _, log = play(llm)

    verified = log.to_dict()["turns"][0]["events"][1]
    assert (verified["problem"], verified["answer"], verified["code"]) == (
        "What is the answer?", "42", "print(42)",
    )  # fmt: skip


def test_retry_logs_the_first_attempt_and_backfire_logs_the_last() -> None:
    first = good_attack(answer="41", problem="first try")
    second = good_attack(answer="40", problem="second try")
    llm = FakeLlm(
        attacks={"alice": [first, second] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3},
    )

    _, log = play(llm)

    events = log.to_dict()["turns"][0]["events"]
    retry, backfire = events[1], events[2]
    assert (retry["type"], retry["problem"], retry["answer"], retry["code"]) == (
        "attack_retry", "first try", "41", "print(42)",
    )  # fmt: skip
    assert (backfire["type"], backfire["problem"], backfire["answer"], backfire["code"]) == (
        "backfire", "second try", "40", "print(42)",
    )  # fmt: skip


def test_backfire_without_a_parsed_attack_has_no_attempt_fields() -> None:
    llm = FakeLlm(
        attacks={
            "alice": ["no tags here", good_attack(), good_attack()],
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    _, log = play(llm)

    backfire = log.to_dict()["turns"][0]["events"][1]
    assert set(backfire) == {"t", "type", "actor", "reason"}


def test_a_shorter_match_ends_after_max_turns_with_the_higher_hp_winning() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("0")] * 3, "bob": [answer("42")] * 3},
    )
    log = BattleLog("m1")

    record = run_match(A, B, llm, SETTINGS, log, random.Random(0), max_turns=2)

    assert [t.attacker for t in record.turns] == ["a", "b"]
    assert record.result.reason == "decision"
    last = log.to_dict()["turns"][-1]["events"][-1]
    assert (last["type"], last["turns"]) == ("match_end", 2)


PANEL = tuple(Fighter(f"ref-{i}", "p", "m", "a careful solver") for i in (1, 2, 3))


def with_panel(replies: list[str], defender: str) -> FakeLlm:
    """alice always attacks with 6 * 7; bob defends with `defender`; each ref gets `replies`."""
    return FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer(defender)] * 3, "bob": [answer(defender)] * 3}
        | {m.name: [answer(r) for r in replies] for m in PANEL},
    )


def first_turn(llm: FakeLlm) -> tuple[list[dict[str, Any]], float]:
    log = BattleLog("m1")
    record = run_match(A, B, llm, SETTINGS, log, random.Random(0), panel=PANEL)
    return log.to_dict()["turns"][0]["events"], record.turns[0].damage


def test_a_hard_problem_hits_harder_and_is_logged_with_the_panel_result() -> None:
    events, damage_dealt = first_turn(with_panel(["0"] * 6, defender="0"))

    assert [e["type"] for e in events] == [
        "attack_start", "attack_verified", "difficulty", "defend_start", "defend_result",
        "hit", "hp",
    ]  # fmt: skip
    difficulty = events[2]
    assert (difficulty["value"], difficulty["failed"], difficulty["answered"]) == (2.0, 3, 3)
    assert [m["name"] for m in difficulty["panel"]] == ["ref-1", "ref-2", "ref-3"]
    assert difficulty["tokens"] == 0
    assert damage_dealt == 40.0 and events[5]["damage"] == 40.0


def test_an_easy_problem_hits_softer() -> None:
    events, damage_dealt = first_turn(with_panel(["42"] * 6, defender="0"))

    assert events[2]["value"] == 0.5
    assert damage_dealt == 10.0


def test_a_blocked_attack_is_still_scored_but_deals_nothing() -> None:
    events, damage_dealt = first_turn(with_panel(["0"] * 6, defender="42"))

    assert [e["type"] for e in events][2:4] == ["difficulty", "defend_start"]
    assert damage_dealt == 0.0


def test_a_backfire_is_not_scored_and_costs_the_default() -> None:
    liar = good_attack(code="print(41)")
    llm = FakeLlm(
        attacks={"alice": [liar] * 6, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("42")] * 3}
        | {m.name: [answer("42")] * 3 for m in PANEL},  # bob's attacks still get scored
    )

    events, damage_dealt = first_turn(llm)

    assert "difficulty" not in [e["type"] for e in events]
    assert damage_dealt == 10.0


def test_without_a_panel_nothing_is_scored() -> None:
    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer("0")] * 3, "bob": [answer("0")] * 3},
    )

    _, log = play(llm)

    assert all("difficulty" not in event_types(log, n) for n in range(1, 4))
    assert log.to_dict()["turns"][0]["events"][4]["damage"] == 20.0
