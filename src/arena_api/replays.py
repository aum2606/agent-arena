import re
from dataclasses import dataclass
from typing import Any

from arena.damage import BACKFIRE_FACTOR, BASE_DAMAGE, DIFFICULTY, STARTING_HP

# Match ids appear in URLs; anything else is rejected before it reaches the database.
VALID_ID = re.compile(r"[A-Za-z0-9_-]+")


class ReplayError(Exception):
    pass


@dataclass(frozen=True)
class Attempt:
    """An attack that failed its check and was retried (D-025)."""

    problem: str
    answer: str
    code: str
    reason: str


@dataclass(frozen=True)
class FighterInfo:
    """From the schema 2 log header; persona is revealed because the match is over."""

    name: str
    provider: str
    model: str
    persona: str


@dataclass(frozen=True)
class TurnView:
    n: int
    attacker: str
    outcome: str  # "hit", "block" or "backfire"
    target: str | None  # who took the damage; None for a block
    damage: float
    damage_math: str
    problem: str | None  # None when the attack never verified
    stated_answer: str | None
    code: str | None  # the attacker's snippet, or reference solution for a code strike
    domain: str  # "math" or "code"; logs from before the code domain are math
    tests: str | None  # code strike only: the hidden test inputs, a JSON list
    defender_answer: str | None
    score: float | None
    timed_out: bool  # the defender timed out or was cut off
    retried: bool  # the attacker's first attempt failed its check (D-025)
    first_attempt: Attempt | None  # what that attempt was (schema 2 logs only)
    failure_reason: str | None
    hp_a: float
    hp_b: float
    duration_ms: int
    difficulty: float | None  # from the panel; None when the problem was not scored (D-036)
    panel_failed: int | None
    panel_answered: int | None


@dataclass(frozen=True)
class ReplaySummary:
    id: str
    winner: str | None
    reason: str | None
    hp_a: float
    hp_b: float
    turn_count: int
    name_a: str | None  # None for schema 1 logs
    name_b: str | None


@dataclass(frozen=True)
class Replay:
    summary: ReplaySummary
    turns: list[TurnView]
    fighter_a: FighterInfo | None
    fighter_b: FighterInfo | None
    max_hp: float  # what a full health bar means


def _damage_math(outcome: str, damage: float, score: float | None, difficulty: float) -> str:
    if outcome == "block":
        return "no damage"
    if outcome == "backfire":
        return f"{BASE_DAMAGE:g} × {DIFFICULTY:g} × {BACKFIRE_FACTOR:g} = {damage:g}"
    return f"{BASE_DAMAGE:g} × {difficulty:g} × (1 − {score or 0.0:g}) = {damage:g}"


def _turn_view(raw: dict[str, Any]) -> TurnView:
    events: list[dict[str, Any]] = raw["events"]
    first = {e["type"]: e for e in reversed(events)}  # earliest event of each type wins
    attacker = first["attack_start"]["actor"]
    outcome = next(kind for kind in ("backfire", "block", "hit") if kind in first)
    # The attempt that ended the turn: the verified one, or the backfired one if it was logged.
    shown = first.get("attack_verified") or (first["backfire"] if outcome == "backfire" else {})
    retry = first.get("attack_retry")
    scored = first.get("difficulty")
    defended = first.get("defend_result")
    hit = first.get("hit")
    hp = first["hp"]
    score = defended["score"] if defended else None
    damage = float(hit["damage"]) if hit else 0.0
    return TurnView(
        n=raw["turn"],
        attacker=attacker,
        outcome=outcome,
        target=hit["target"] if hit else None,
        damage=damage,
        damage_math=_damage_math(outcome, damage, score, scored["value"] if scored else DIFFICULTY),
        problem=shown.get("problem"),
        stated_answer=shown.get("answer"),
        code=shown.get("code"),
        domain=shown.get("domain", "math"),
        tests=shown.get("tests"),
        defender_answer=defended["answer"] if defended else None,
        score=score,
        timed_out="timeout" in first and attacker != first["timeout"]["actor"],
        retried=retry is not None,
        first_attempt=Attempt(retry["problem"], retry["answer"], retry["code"], retry["reason"])
        if retry and "problem" in retry
        else None,
        failure_reason=first["backfire"]["reason"] if outcome == "backfire" else None,
        hp_a=hp["a"],
        hp_b=hp["b"],
        duration_ms=events[-1]["t"],
        difficulty=scored["value"] if scored else None,
        panel_failed=scored["failed"] if scored else None,
        panel_answered=scored["answered"] if scored else None,
    )


def parse_replay(replay_id: str, raw: dict[str, Any]) -> Replay:
    """The reveal-panel view of a battle log (schema 1 or 2)."""
    try:
        turns = [_turn_view(t) for t in raw["turns"]]
        ended: dict[str, Any] = next(
            (e for e in raw["turns"][-1]["events"] if e["type"] == "match_end"), {}
        )
        header = raw.get("fighters")  # schema 2 only
        fighter_a = FighterInfo(**header["a"]) if header else None
        fighter_b = FighterInfo(**header["b"]) if header else None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ReplayError(f"replay {replay_id!r} is unreadable: {exc!r}") from exc
    summary = ReplaySummary(
        id=replay_id,
        winner=ended.get("winner"),
        reason=ended.get("reason"),
        hp_a=turns[-1].hp_a,
        hp_b=turns[-1].hp_b,
        turn_count=len(turns),
        name_a=fighter_a.name if fighter_a else None,
        name_b=fighter_b.name if fighter_b else None,
    )
    return Replay(summary, turns, fighter_a, fighter_b, STARTING_HP)
