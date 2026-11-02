import asyncio
from typing import Any

import pytest

from arena.config import Config, Settings
from arena.llm import Completion, LlmError
from arena.models import Fighter
from arena.prompts import ATTACK_REQUEST
from arena_api import store
from arena_api.jobs import play_match, startup

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    defender_max_tokens=128,
    snippet_timeout_s=10.0,
    call_delay_s=0.0,
    max_retries=0,
    backoff_base_s=0.0,
)
CONFIG = Config(
    SETTINGS,
    {},
    {
        "alice": Fighter("alice", "p", "m", "persona a"),
        "bob": Fighter("bob", "p", "m", "persona b"),
    },
)


def blocking(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
    """Every attack is the verified 6 * 7; every defense answers 42, so every attack is blocked."""
    if user.endswith(ATTACK_REQUEST):
        text = "<problem>6 * 7?</problem><answer>42</answer><code>print(42)</code>"
        return Completion(text, False)
    return Completion("<answer>42</answer>", False)


def run(complete: Any, match_id: str = "m1", config: Config = CONFIG) -> None:
    asyncio.run(play_match({"config": config, "complete": complete}, match_id))


def test_a_queued_match_is_played_and_stored(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    run(blocking)

    row = store.get_match("m1")
    assert row is not None and (row.status, row.error) == ("finished", None)
    (summary,) = store.list_finished()
    assert (summary.name_a, summary.name_b, summary.turn_count) == ("alice", "bob", 6)
    log = store.get_log("m1")
    assert log is not None and log["fighters"]["a"]["persona"] == "persona a"


def test_a_provider_error_fails_the_match_with_its_reason(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    def rate_limited(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        raise LlmError("groq rate limited after 8 retries")

    run(rate_limited)

    row = store.get_match("m1")
    assert row is not None and row.status == "failed"
    assert row.error == "groq rate limited after 8 retries"
    assert store.list_finished() == []


def test_a_fighter_that_left_the_config_fails_the_match(database: str) -> None:
    store.create_match("m1", "alice", "gone")

    run(blocking)

    row = store.get_match("m1")
    assert row is not None and row.status == "failed"
    assert row.error is not None and "gone" in row.error


def test_an_unexpected_error_is_recorded_and_raised(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    def broken(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        raise ZeroDivisionError("boom")

    with pytest.raises(ZeroDivisionError):
        run(broken)

    row = store.get_match("m1")
    assert row is not None and row.status == "failed"
    assert row.error is not None and "ZeroDivisionError" in row.error


def test_a_match_that_is_not_queued_is_never_played_twice(database: str) -> None:
    store.create_match("m1", "alice", "bob")
    store.mark_running("m1")

    def forbidden(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        raise AssertionError("the match was played again")

    run(forbidden)

    row = store.get_match("m1")
    assert row is not None and row.status == "running"


def test_an_unknown_match_id_is_ignored(database: str) -> None:
    run(blocking, "nope")

    assert store.get_match("nope") is None


def test_startup_loads_the_config_and_fails_stale_matches(
    database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    path = tmp_path / "fighters.toml"
    path.write_text(
        """
[settings]
turn_time_limit_s = 30.0
turn_max_tokens = 256
defender_max_tokens = 128
snippet_timeout_s = 5.0
call_delay_s = 0.0
max_retries = 0
backoff_base_s = 0.0

[providers.p]
base_url = "https://example.test/v1"
api_key_env = "P_API_KEY"

[[fighters]]
name = "alice"
provider = "p"
model = "m"
persona = "persona a"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FIGHTERS_CONFIG", str(path))
    store.create_match("stuck", "alice", "bob")
    store.mark_running("stuck")
    ctx: dict[str, Any] = {}

    asyncio.run(startup(ctx))

    assert list(ctx["config"].fighters) == ["alice"]
    assert callable(ctx["complete"])
    stuck = store.get_match("stuck")
    assert stuck is not None and stuck.status == "failed"
