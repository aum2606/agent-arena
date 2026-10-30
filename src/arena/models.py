from dataclasses import dataclass
from typing import Literal

Side = Literal["a", "b"]


@dataclass(frozen=True)
class MatchResult:
    """winner is None for a draw."""

    winner: Side | None
    reason: Literal["ko", "decision"]
