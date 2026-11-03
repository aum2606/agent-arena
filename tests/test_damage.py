import pytest

from arena.damage import (
    BACKFIRE_FACTOR,
    BASE_DAMAGE,
    DIFFICULTY,
    DIFFICULTY_MAX,
    DIFFICULTY_MIN,
    MAX_TURNS,
    STARTING_HP,
    apply_damage,
    backfire_damage,
    damage,
    difficulty_from_panel,
    match_result,
)
from arena.models import MatchResult


def test_phase0_constants() -> None:
    assert (STARTING_HP, BASE_DAMAGE, DIFFICULTY, MAX_TURNS) == (100.0, 20.0, 1.0, 6)


def test_backfire_costs_the_attacker_half_the_damage() -> None:
    assert BACKFIRE_FACTOR == 0.5
    assert backfire_damage(BASE_DAMAGE, DIFFICULTY) == 10.0
    assert backfire_damage(BASE_DAMAGE, 2.0) == 20.0


@pytest.mark.parametrize(
    ("difficulty", "score", "expected"),
    [(1.0, 0.0, 20.0), (1.0, 1.0, 0.0), (1.0, 0.25, 15.0), (2.0, 0.0, 40.0)],
)
def test_damage(difficulty: float, score: float, expected: float) -> None:
    assert damage(BASE_DAMAGE, difficulty, score) == expected


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_damage_rejects_score_outside_unit_range(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        damage(BASE_DAMAGE, DIFFICULTY, score)


def test_apply_damage_reduces_hp() -> None:
    assert apply_damage(100.0, 20.0) == 80.0


def test_apply_damage_floors_at_zero() -> None:
    assert apply_damage(10.0, 20.0) == 0.0


def test_match_continues_while_both_alive_and_rounds_left() -> None:
    assert match_result(80.0, 60.0, turns_played=3, max_turns=6) is None


def test_knockout_of_a_means_b_wins() -> None:
    result = match_result(0.0, 40.0, turns_played=4, max_turns=6)
    assert result is not None
    assert (result.winner, result.reason) == ("b", "ko")


def test_knockout_of_b_means_a_wins() -> None:
    assert match_result(40.0, 0.0, turns_played=4, max_turns=6) == MatchResult("a", "ko")


def test_knockout_on_final_turn_is_still_a_knockout() -> None:
    assert match_result(0.0, 40.0, turns_played=6, max_turns=6) == MatchResult("b", "ko")


def test_decision_goes_to_higher_hp() -> None:
    assert match_result(60.0, 80.0, turns_played=6, max_turns=6) == MatchResult("b", "decision")


def test_equal_hp_after_last_turn_is_a_draw() -> None:
    assert match_result(80.0, 80.0, turns_played=6, max_turns=6) == MatchResult(None, "decision")


def test_difficulty_range_is_the_specs() -> None:
    assert (DIFFICULTY_MIN, DIFFICULTY_MAX) == (0.5, 2.0)
    assert DIFFICULTY_MIN <= DIFFICULTY <= DIFFICULTY_MAX


@pytest.mark.parametrize(
    ("failed", "answered", "expected"),
    [(0, 3, 0.5), (1, 3, 1.0), (2, 3, 1.5), (3, 3, 2.0), (1, 2, 1.25), (0, 1, 0.5), (1, 1, 2.0)],
)
def test_difficulty_grows_with_the_share_of_the_panel_that_failed(
    failed: int, answered: int, expected: float
) -> None:
    assert difficulty_from_panel(failed, answered) == expected


@pytest.mark.parametrize(("failed", "answered"), [(1, 0), (0, 0), (-1, 3), (4, 3)])
def test_impossible_panel_counts_are_rejected(failed: int, answered: int) -> None:
    with pytest.raises(ValueError, match="panel"):
        difficulty_from_panel(failed, answered)
