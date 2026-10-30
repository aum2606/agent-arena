from dataclasses import dataclass
from typing import Literal

Side = Literal["a", "b"]


@dataclass(frozen=True)
class Fighter:
    name: str
    provider: str
    model: str
    persona: str


@dataclass(frozen=True)
class Attack:
    problem: str
    answer: str
    snippet: str


@dataclass(frozen=True)
class MatchResult:
    """winner is None for a draw."""

    winner: Side | None
    reason: Literal["ko", "decision"]
