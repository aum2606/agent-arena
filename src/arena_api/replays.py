import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.damage import BACKFIRE_FACTOR, BASE_DAMAGE, DIFFICULTY

logger = logging.getLogger(__name__)

DEFAULT_LOGS_DIR = "runs/logs"
# Ids become file names, so anything that could leave the logs folder is rejected.
_ID = re.compile(r"[A-Za-z0-9_-]+")


class ReplayError(Exception):
    pass


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
    defender_answer: str | None
    score: float | None
    timed_out: bool  # the defender timed out or was cut off
    retried: bool  # the attacker's first attempt failed its check (D-025)
    failure_reason: str | None
    hp_a: float
    hp_b: float
    duration_ms: int


@dataclass(frozen=True)
class ReplaySummary:
    id: str
    winner: str | None
    reason: str | None
    hp_a: float
    hp_b: float
    turn_count: int


@dataclass(frozen=True)
class Replay:
    summary: ReplaySummary
    turns: list[TurnView]


def logs_dir() -> Path:
    return Path(os.environ.get("ARENA_LOGS_DIR", DEFAULT_LOGS_DIR))


def _damage_math(outcome: str, damage: float, score: float | None) -> str:
    if outcome == "block":
        return "no damage"
    if outcome == "backfire":
        return f"{BASE_DAMAGE:g} × {DIFFICULTY:g} × {BACKFIRE_FACTOR:g} = {damage:g}"
    return f"{BASE_DAMAGE:g} × {DIFFICULTY:g} × (1 − {score or 0.0:g}) = {damage:g}"


def _turn_view(raw: dict[str, Any]) -> TurnView:
    events: list[dict[str, Any]] = raw["events"]
    first = {e["type"]: e for e in reversed(events)}  # earliest event of each type wins
    attacker = first["attack_start"]["actor"]
    outcome = next(kind for kind in ("backfire", "block", "hit") if kind in first)
    verified = first.get("attack_verified")
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
        damage_math=_damage_math(outcome, damage, score),
        problem=verified["problem"] if verified else None,
        stated_answer=verified["answer"] if verified else None,
        defender_answer=defended["answer"] if defended else None,
        score=score,
        timed_out="timeout" in first and attacker != first["timeout"]["actor"],
        retried="attack_retry" in first,
        failure_reason=first["backfire"]["reason"] if outcome == "backfire" else None,
        hp_a=hp["a"],
        hp_b=hp["b"],
        duration_ms=events[-1]["t"],
    )


def _parse(replay_id: str, path: Path) -> Replay:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        turns = [_turn_view(t) for t in raw["turns"]]
        ended: dict[str, Any] = next(
            (e for e in raw["turns"][-1]["events"] if e["type"] == "match_end"), {}
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError, StopIteration) as exc:
        raise ReplayError(f"replay {replay_id!r} is unreadable: {exc!r}") from exc
    summary = ReplaySummary(
        id=replay_id,
        winner=ended.get("winner"),
        reason=ended.get("reason"),
        hp_a=turns[-1].hp_a,
        hp_b=turns[-1].hp_b,
        turn_count=len(turns),
    )
    return Replay(summary, turns)


def list_replays(directory: Path) -> list[ReplaySummary]:
    found: list[ReplaySummary] = []
    for path in sorted(directory.glob("*.json")):
        try:
            found.append(_parse(path.stem, path).summary)
        except ReplayError as exc:
            logger.warning("skipping %s: %s", path.name, exc)
    return found


def get_replay(directory: Path, replay_id: str) -> Replay | None:
    path = directory / f"{replay_id}.json"
    if not _ID.fullmatch(replay_id) or not path.is_file():
        return None
    return _parse(replay_id, path)
