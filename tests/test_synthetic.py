import random

import pytest

from arena.models import Fighter
from arena.prompts import ATTACK_REQUEST, defense_prompts, parse_attack, parse_defense
from arena.stats import compute_stats
from arena.synthetic import (
    ADVANTAGES,
    SKILLS,
    Skill,
    SyntheticLlm,
    format_sweep,
    play_synthetic,
    success_probability,
    sweep,
    synthetic_verify,
)

FIGHTER = Fighter("a", "synthetic", "synthetic", "")
STRONG = Skill(5.0, 0.0)  # succeeds almost surely at any difficulty
WEAK = Skill(-5.0, 0.0)  # fails almost surely


def test_success_probability_is_a_logistic_curve_around_the_difficulty() -> None:
    assert success_probability(0.5, 0.5) == pytest.approx(0.5)
    assert success_probability(0.7, 0.5) > 0.85
    assert success_probability(0.3, 0.5) < 0.15
    assert success_probability(0.6, 0.5) < success_probability(0.8, 0.5)


def test_strong_attacker_reply_verifies_and_carries_its_difficulty() -> None:
    llm = SyntheticLlm({"a": STRONG}, difficulty=0.5, rng=random.Random(0))

    attack = parse_attack(llm.complete(FIGHTER, "", ATTACK_REQUEST).text)

    assert synthetic_verify(attack.answer, attack.snippet, 1.0).passed
    assert "d=" in attack.problem


def test_weak_attacker_reply_fails_verification() -> None:
    llm = SyntheticLlm({"a": WEAK}, difficulty=0.5, rng=random.Random(0))

    attack = parse_attack(llm.complete(FIGHTER, "", ATTACK_REQUEST).text)
    check = synthetic_verify(attack.answer, attack.snippet, 1.0)

    assert not check.passed
    assert "mismatch" in check.reason


def test_attack_bonus_raises_verification_odds_only_for_attacks() -> None:
    llm = SyntheticLlm({"a": Skill(-0.5, 5.5)}, difficulty=0.5, rng=random.Random(0))
    attack = parse_attack(llm.complete(FIGHTER, "", ATTACK_REQUEST).text)
    assert synthetic_verify(attack.answer, attack.snippet, 1.0).passed

    _, user = defense_prompts(FIGHTER, attack.problem)
    assert parse_defense(llm.complete(FIGHTER, "", user).text) == "2"  # skill -0.5 alone fails


@pytest.mark.parametrize(("skill", "expected"), [(STRONG, "1"), (WEAK, "2")])
def test_defender_answers_by_the_problem_difficulty(skill: Skill, expected: str) -> None:
    llm = SyntheticLlm({"a": skill}, difficulty=0.5, rng=random.Random(0))
    _, user = defense_prompts(FIGHTER, "Synthetic problem d=0.500 #1")

    assert parse_defense(llm.complete(FIGHTER, "", user).text) == expected


def test_synthetic_verify_rejects_foreign_snippets() -> None:
    assert not synthetic_verify("1", "import os", 1.0).passed


def test_dominant_attacker_never_loses_hp_in_its_own_turns() -> None:
    records = play_synthetic((STRONG, WEAK), difficulty=0.5, matches=3, seed=1)

    for record in records:
        # A hits on turns 1, 3, 5 (3 x 20); B backfires on turns 2, 4, 6 (3 x 10).
        assert (record.hp_a, record.hp_b) == (100.0, 10.0)
        assert record.result.winner == "a"


def test_equal_skills_cap_the_attacker_near_a_quarter_of_turns() -> None:
    records = play_synthetic((Skill(0.6, 0.0), Skill(0.6, 0.0)), 0.5, matches=200, seed=3)

    assert compute_stats(records).attacker_win_rate < 0.30


def test_attacker_advantage_raises_the_attacker_win_rate() -> None:
    hard = 0.7
    base = play_synthetic((Skill(0.6, 0.0), Skill(0.6, 0.0)), hard, matches=200, seed=5)
    boosted = play_synthetic((Skill(0.6, 0.3), Skill(0.6, 0.3)), hard, matches=200, seed=5)

    assert compute_stats(boosted).attacker_win_rate > compute_stats(base).attacker_win_rate + 0.2


def test_sweep_has_a_cell_for_every_skill_and_advantage() -> None:
    table = sweep(matches=2, difficulty=0.5, seed=0)

    assert set(table) == {(s, a) for s in SKILLS for a in ADVANTAGES}
    assert all(0.0 <= rate <= 1.0 for rate in table.values())


def test_format_sweep_marks_only_cells_where_the_gate_passes() -> None:
    rates = {(s, a): 0.2 for s in SKILLS for a in ADVANTAGES}
    rates[(SKILLS[1], ADVANTAGES[2])] = 0.5

    text = format_sweep(rates)

    assert text.count("*") == 2  # one marked cell plus the legend
    assert "50%*" in text
    assert "20%*" not in text
