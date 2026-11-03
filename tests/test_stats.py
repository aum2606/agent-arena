from pathlib import Path
from typing import Literal

import pytest

from arena.models import MatchRecord, MatchResult, TurnResult
from arena.stats import (
    ResultsError,
    append_record,
    attack_outcomes,
    compute_stats,
    format_stats,
    load_records,
    wilson_interval,
)

type Outcome = Literal["hit", "block", "backfire"]


def record(outcomes: list[Outcome], result: MatchResult, hp: tuple[float, float]) -> MatchRecord:
    turns = []
    for i, outcome in enumerate(outcomes, start=1):
        attacker = "a" if i % 2 else "b"
        defender = "b" if i % 2 else "a"
        target = attacker if outcome == "backfire" else defender
        turns.append(TurnResult(i, attacker, outcome, target, 0.0 if outcome == "block" else 20.0))
    return MatchRecord("alice", "bob", turns, hp[0], hp[1], result)


def many(n: int, outcomes: list[Outcome]) -> list[MatchRecord]:
    return [record(outcomes, MatchResult(None, "decision"), (60.0, 60.0)) for _ in range(n)]


def test_compute_stats() -> None:
    records = [
        record(["hit", "block", "backfire", "hit"], MatchResult("a", "decision"), (80.0, 40.0)),
        record(["hit", "hit"], MatchResult(None, "decision"), (80.0, 60.0)),
        record(["backfire"], MatchResult("b", "ko"), (0.0, 100.0)),
    ]

    stats = compute_stats(records)

    assert (stats.matches, stats.turns) == (3, 7)
    assert (stats.hits, stats.blocks, stats.backfires) == (4, 1, 2)
    assert stats.attacker_win_rate == pytest.approx(4 / 7)
    assert stats.defender_win_rate == pytest.approx(3 / 7)
    assert stats.backfire_rate == pytest.approx(2 / 7)
    assert stats.average_damage_per_turn == pytest.approx(120 / 7)
    assert stats.average_match_length == pytest.approx(7 / 3)
    assert (stats.kos, stats.decisions, stats.draws) == (1, 1, 1)


def test_gate_passes_when_neither_role_exceeds_70_percent() -> None:
    stats = compute_stats(many(100, ["hit", "block", "hit", "block"]))
    assert "Gate: PASS" in format_stats(stats)


def test_gate_fails_and_names_the_dominant_role() -> None:
    stats = compute_stats(many(100, ["hit", "hit", "hit", "block"]))
    text = format_stats(stats)
    assert "Gate: FAIL" in text
    assert "attacker" in text.split("Gate:")[1]


def test_gate_is_incomplete_below_100_matches() -> None:
    text = format_stats(compute_stats(many(3, ["hit", "block"])))
    assert "Gate: INCOMPLETE (3/100 matches)" in text


def test_format_stats_lines() -> None:
    lines = format_stats(compute_stats(many(2, ["hit", "block", "backfire"]))).splitlines()
    assert lines[:6] == [
        "Matches: 2, turns: 6",
        "Attacker wins 33.3% of turns (hit 2)",
        "Defender wins 66.7% of turns (block 2, backfire 2)",
        "Backfire rate: 33.3%",
        "Average damage per turn: 13.3",
        "Average match length: 3.0 turns",
    ]
    assert lines[6] == "Endings: KO 0, decision 0, draw 2"


def test_append_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "sim.jsonl"
    first = record(["hit", "block"], MatchResult("a", "decision"), (100.0, 80.0))
    second = record(["backfire"], MatchResult("b", "ko"), (0.0, 100.0))

    append_record(path, first)
    append_record(path, second)

    assert load_records(path) == [first, second]


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_records(tmp_path / "nope.jsonl") == []


def test_load_reports_the_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "sim.jsonl"
    append_record(path, record(["hit"], MatchResult("a", "decision"), (100.0, 80.0)))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"fighter_a": "alice", "tru')

    with pytest.raises(ResultsError, match=r"sim\.jsonl:2"):
        load_records(path)


def test_attack_outcomes_lists_only_the_fighters_own_attacks_in_order() -> None:
    first = record(
        ["hit", "block", "backfire", "block"], MatchResult("a", "decision"), (80.0, 60.0)
    )
    second = MatchRecord(
        "bob",
        "alice",
        [TurnResult(1, "a", "block", "b", 0.0), TurnResult(2, "b", "hit", "a", 20.0)],
        100.0,
        80.0,
        MatchResult("a", "decision"),
    )

    # alice is fighter A in the first match (attacks on turns 1 and 3) and fighter B in the second.
    assert attack_outcomes([first, second], "alice") == ["hit", "backfire", "hit"]
    assert attack_outcomes([first, second], "bob") == ["block", "block", "block"]


def test_attack_outcomes_for_an_unknown_fighter_is_empty() -> None:
    assert (
        attack_outcomes([record(["hit"], MatchResult("a", "decision"), (80.0, 60.0))], "zed") == []
    )


def test_wilson_interval_brackets_the_rate_and_widens_with_less_data() -> None:
    low, high = wilson_interval(50, 100)
    assert (round(low, 3), round(high, 3)) == (0.404, 0.596)
    assert wilson_interval(0, 10)[0] == 0.0
    assert round(wilson_interval(0, 10)[1], 3) == 0.278
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_attacks_that_reached_a_defender_exclude_backfires() -> None:
    stats = compute_stats(many(2, ["hit", "block", "block", "backfire"]))

    assert stats.verified_hit_rate == pytest.approx(2 / 6)
    assert compute_stats(many(1, ["backfire"])).verified_hit_rate is None


def test_the_report_gives_95_percent_intervals_and_the_verified_hit_rate() -> None:
    lines = format_stats(compute_stats(many(2, ["hit", "block", "block", "backfire"]))).splitlines()

    assert "Attacks that reached a defender: 6, hit rate 33.3%" in lines
    assert any(line.startswith("95% intervals: attacker ") for line in lines)


def test_gate_is_inconclusive_when_the_interval_straddles_70_percent() -> None:
    hits_70 = ["hit"] * 7 + ["block"] * 3
    text = format_stats(compute_stats(many(100, hits_70)))

    assert "Gate: INCONCLUSIVE" in text


def test_gate_fail_message_gives_the_interval() -> None:
    text = format_stats(compute_stats(many(100, ["hit", "hit", "hit", "block"])))

    assert "Gate: FAIL (attacker wins 75.0% of turns, 95% interval" in text


def test_an_incomplete_run_says_when_it_can_no_longer_pass() -> None:
    mostly_blocked = ["block"] * 5 + ["hit"]
    text = format_stats(compute_stats(many(40, mostly_blocked)))

    assert "Gate: INCOMPLETE (40/100 matches); cannot pass: defender wins at least" in text


def test_an_incomplete_run_that_could_still_pass_does_not_say_otherwise() -> None:
    text = format_stats(compute_stats(many(40, ["hit", "block"])))

    assert "cannot pass" not in text
