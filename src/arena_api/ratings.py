from collections.abc import Sequence
from dataclasses import dataclass

# Rule numbers for ranked play (D-043).
START_RATING = 1200.0
K_FACTOR = 32.0
_SCALE = 400.0


@dataclass(frozen=True)
class Candidate:
    """A fighter that could be paired: its latest version, owner and standing."""

    fighter_id: int
    owner_id: int
    rating: float
    games: int
    version: int
    name: str


def expected_score(rating: float, opponent: float) -> float:
    """The Elo chance that a fighter at `rating` beats one at `opponent` (a draw counts half)."""
    return 1 / (1 + 10 ** ((opponent - rating) / _SCALE))


def rate(a: float, b: float, score_a: float) -> tuple[float, float]:
    """New ratings after a match; `score_a` is 1 for an A win, 0.5 for a draw, 0 for a B win."""
    change = K_FACTOR * (score_a - expected_score(a, b))
    return a + change, b - change


def pick_opponent(
    owner_id: int, rating: float, candidates: Sequence[Candidate]
) -> Candidate | None:
    """The closest rating among other owners' fighters (the collusion rule); ties go to the
    fighter with fewer games, then the lower id, so repeat pairings spread out."""
    others = [c for c in candidates if c.owner_id != owner_id]
    return min(others, key=lambda c: (abs(c.rating - rating), c.games, c.fighter_id), default=None)
