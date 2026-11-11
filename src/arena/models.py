from dataclasses import dataclass
from typing import Literal

Side = Literal["a", "b"]
Outcome = Literal["hit", "block", "backfire"]
Domain = Literal["math", "code"]


@dataclass(frozen=True)
class Fighter:
    name: str
    provider: str
    model: str
    persona: str
    # How hard a reasoning model thinks, passed to the provider as is: the allowed values differ by
    # model (D-055). None leaves the provider's default.
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class Attack:
    problem: str
    answer: str
    snippet: str  # math: prints the answer; code: the reference solution
    domain: Domain = "math"
    inputs: str = ""  # code only: the hidden test inputs, a JSON list of argument lists


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
