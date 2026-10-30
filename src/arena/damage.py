from arena.models import MatchResult

MAX_TURNS = 6  # a round is one turn (D-006)
STARTING_HP = 100.0
BASE_DAMAGE = 20.0
DIFFICULTY = 1.0  # fixed in Phase 0; a difficulty scorer comes later


def damage(base: float, difficulty: float, score: float) -> float:
    """Damage dealt for a defender score in [0, 1]."""
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    return base * difficulty * (1.0 - score)


def apply_damage(hp: float, amount: float) -> float:
    return max(hp - amount, 0.0)


def match_result(hp_a: float, hp_b: float, turns_played: int, max_turns: int) -> MatchResult | None:
    """None while the match should continue."""
    if hp_a <= 0:
        return MatchResult("b", "ko")
    if hp_b <= 0:
        return MatchResult("a", "ko")
    if turns_played < max_turns:
        return None
    if hp_a == hp_b:
        return MatchResult(None, "decision")
    return MatchResult("a" if hp_a > hp_b else "b", "decision")
