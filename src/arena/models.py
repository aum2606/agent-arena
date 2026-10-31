from dataclasses import dataclass
from typing import Literal

Side = Literal["a", "b"]
Outcome = Literal["hit", "block", "backfire"]


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


@dataclass(frozen=True)
class TurnResult:
    """outcome "hit" means the defender failed; "backfire" means the attacker's own check failed."""

    turn: int
    attacker: Side
    outcome: Outcome
    target: Side  # who takes `damage`
    damage: float


@dataclass(frozen=True)
class MatchRecord:
    fighter_a: str
    fighter_b: str
    turns: list[TurnResult]
    hp_a: float
    hp_b: float
    result: MatchResult
