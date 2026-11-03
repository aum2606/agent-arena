from arena.models import MatchResult

MAX_TURNS = 6  # a round is one turn (D-006)
STARTING_HP = 100.0
BASE_DAMAGE = 20.0
DIFFICULTY = 1.0  # used when a problem is not scored by the panel, and for backfires
DIFFICULTY_MIN = 0.5  # every panel member solved it
DIFFICULTY_MAX = 2.0  # every member failed it
BACKFIRE_FACTOR = 0.5  # share of normal damage an attacker takes on a backfire (D-013)


def damage(base: float, difficulty: float, score: float) -> float:
    """Damage dealt for a defender score in [0, 1]."""
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    return base * difficulty * (1.0 - score)


def backfire_damage(base: float, difficulty: float) -> float:
    """Damage the attacker takes when its own problem fails verification."""
    return base * difficulty * BACKFIRE_FACTOR


def difficulty_from_panel(failed: int, answered: int) -> float:
    """Linear from DIFFICULTY_MIN to DIFFICULTY_MAX in the share of answering members failing."""
    if answered <= 0 or not 0 <= failed <= answered:
        raise ValueError(f"bad panel counts: {failed} failed of {answered} answered")
    return DIFFICULTY_MIN + (DIFFICULTY_MAX - DIFFICULTY_MIN) * failed / answered


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
