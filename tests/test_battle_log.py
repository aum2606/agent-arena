import json
from pathlib import Path

import pytest

from arena.battle_log import EVENT_TYPES, SCHEMA_VERSION, BattleLog
from arena.models import Fighter


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_event_types_are_the_phase0_spec_plus_attack_retry_and_difficulty() -> None:
    expected = {
        "attack_start",
        "attack_verified",
        "attack_retry",
        "difficulty",
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
    assert expected == EVENT_TYPES


def test_events_carry_ms_since_turn_start() -> None:
    clock = FakeClock()
    log = BattleLog("m1", clock)
    log.start_turn(1)
    log.emit("attack_start", actor="a")
    clock.now += 1.25
    log.emit("attack_verified", actor="a")

    events = log.to_dict()["turns"][0]["events"]
    assert events == [
        {"t": 0, "type": "attack_start", "actor": "a"},
        {"t": 1250, "type": "attack_verified", "actor": "a"},
    ]


def test_new_turn_resets_the_clock() -> None:
    clock = FakeClock()
    log = BattleLog("m1", clock)
    log.start_turn(1)
    clock.now += 5
    log.emit("hit", target="b", damage=20.0)
    log.start_turn(2)
    clock.now += 0.5
    log.emit("block", actor="a")

    turns = log.to_dict()["turns"]
    assert [turn["turn"] for turn in turns] == [1, 2]
    assert turns[0]["events"][0]["t"] == 5000
    assert turns[1]["events"][0]["t"] == 500


def test_unknown_event_type_is_rejected() -> None:
    log = BattleLog("m1")
    log.start_turn(1)
    with pytest.raises(ValueError, match="counter"):
        log.emit("counter")


def test_emit_before_start_turn_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="start_turn"):
        BattleLog("m1").emit("hp")


def test_write_creates_parent_dirs_and_round_trips(tmp_path: Path) -> None:
    log = BattleLog("m1")
    log.start_turn(1)
    log.emit("hp", a=100.0, b=80.0)
    path = tmp_path / "runs" / "m1.json"

    log.write(path)

    assert json.loads(path.read_text(encoding="utf-8")) == log.to_dict()
    assert log.to_dict()["match_id"] == "m1"


def test_log_header_names_the_schema_and_both_fighters() -> None:
    alice = Fighter("alice", "groq", "model-a", "You are bold.")
    bob = Fighter("bob", "gemini", "model-b", "You are careful.")
    log = BattleLog("m1")

    log.record_fighters(alice, bob)

    data = log.to_dict()
    assert data["schema"] == SCHEMA_VERSION == 2
    assert data["fighters"] == {
        "a": {"name": "alice", "provider": "groq", "model": "model-a", "persona": "You are bold."},
        "b": {
            "name": "bob",
            "provider": "gemini",
            "model": "model-b",
            "persona": "You are careful.",
        },
    }
