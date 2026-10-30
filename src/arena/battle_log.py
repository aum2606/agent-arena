import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

EVENT_TYPES = frozenset(
    {
        "attack_start",
        "attack_verified",
        "backfire",
        "defend_start",
        "defend_result",
        "hit",
        "block",
        "timeout",
        "hp",
        "knockout",
        "match_end",
    }
)


class BattleLog:
    """Per-turn event list; each event's `t` is ms since that turn started."""

    def __init__(self, match_id: str, clock: Callable[[], float] = time.monotonic) -> None:
        self._match_id = match_id
        self._clock = clock
        self._turns: list[dict[str, Any]] = []
        self._turn_started = 0.0

    def start_turn(self, turn: int) -> None:
        self._turn_started = self._clock()
        self._turns.append({"turn": turn, "events": []})

    def emit(self, event: str, **fields: Any) -> None:
        if event not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event}")
        if not self._turns:
            raise RuntimeError("call start_turn before emit")
        t = int((self._clock() - self._turn_started) * 1000)
        self._turns[-1]["events"].append({"t": t, "type": event, **fields})

    def to_dict(self) -> dict[str, Any]:
        return {"match_id": self._match_id, "turns": self._turns}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
