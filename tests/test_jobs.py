import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena.config import Config, Provider, Settings
from arena.llm import Completion, LlmError, LlmTimeout
from arena.models import Fighter
from arena.prompts import ATTACK_REQUEST
from arena_api import fighters, store
from arena_api.jobs import SPARRING_TURNS, play_match, startup

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
    {"groq": Provider("https://groq.test/v1", "GROQ_API_KEY")},
    {
        "alice": Fighter("alice", "p", "m", "persona a"),
        "bob": Fighter("bob", "p", "m", "persona b"),
        "house": Fighter("house", "groq", "m", "the house bot"),
    },
    house_bot="house",
)


def blocking(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
    """Every attack is the verified 6 * 7; every defense answers 42, so every attack is blocked."""
    if user.endswith(ATTACK_REQUEST):
        text = "<problem>6 * 7?</problem><answer>42</answer><code>print(42)</code>"
        return Completion(text, False)
    return Completion("<answer>42</answer>", False)


def run(
    complete: Any, match_id: str = "m1", config: Config = CONFIG, keys_seen: list[Any] | None = None
) -> None:
    def complete_with(keys: Any) -> Any:
        if keys_seen is not None:
            keys_seen.append(dict(keys))
        return complete

    asyncio.run(play_match({"config": config, "complete_with": complete_with}, match_id))


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
    assert callable(ctx["complete_with"])
    stuck = store.get_match("stuck")
    assert stuck is not None and stuck.status == "failed"


KEY = "gsk_test_abcdefghij1234"


class Spar:
    """A user's fighter, ada/rex, ready to spar against the house bot."""

    def __init__(self, client: TestClient, match_id: str = "s1") -> None:
        body = {
            "name": "rex", "provider": "groq", "model": "llama-test",
            "persona": "You are bold.", "api_key": KEY,
        }  # fmt: skip
        self.fighter_id = int(client.post("/fighters", json=body).json()["id"])
        user_id = client.get("/auth/me").json()["id"]
        self.match_id = match_id
        store.create_match(
            match_id, "ada/rex", "house", mode="sparring", requested_by=user_id,
            fighter_id=self.fighter_id, fighter_version=1,
        )  # fmt: skip

    def verified(self) -> bool:
        with store.connect() as conn:
            row = conn.execute("SELECT verified_at FROM fighter_versions").fetchone()
        return bool(row and row["verified_at"])


def test_a_spar_plays_a_short_match_with_the_users_own_key(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))
    keys_seen: list[Any] = []

    run(blocking, spar.match_id, keys_seen=keys_seen)

    row = store.get_match(spar.match_id)
    assert row is not None and (row.status, row.error) == ("finished", None)
    log = store.get_log(spar.match_id)
    assert log is not None and len(log["turns"]) == SPARRING_TURNS == 3
    assert [log["fighters"][s]["name"] for s in "ab"] == ["ada/rex", "house"]
    assert log["fighters"]["a"]["persona"] == "You are bold."
    assert keys_seen == [{"ada/rex": KEY}]  # only the user's fighter gets the user's key
    assert KEY not in str(log)  # the key is never in a stored battle log


def test_a_spar_where_the_fighter_answered_marks_that_version_verified(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))

    run(blocking, spar.match_id)

    assert spar.verified() is True


def test_a_spar_where_the_fighter_never_replied_is_played_but_not_verified(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))

    def silent(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        if fighter.name == "ada/rex":
            raise LlmTimeout("no answer")
        return blocking(fighter, system, user, max_tokens)

    run(silent, spar.match_id)

    row = store.get_match(spar.match_id)
    assert row is not None and row.status == "finished"
    assert spar.verified() is False


def test_a_provider_error_fails_the_spar_and_never_shows_the_key(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))

    def rejected(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        raise LlmError(f"groq returned HTTP 401: Incorrect API key provided: {KEY}")

    run(rejected, spar.match_id)

    row = store.get_match(spar.match_id)
    assert row is not None and row.status == "failed"
    assert row.error is not None and KEY not in row.error and "[key]" in row.error
    assert spar.verified() is False


def test_a_spar_fails_cleanly_when_its_provider_left_the_config(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))
    no_groq = Config(SETTINGS, {}, CONFIG.fighters, house_bot="house")

    run(blocking, spar.match_id, config=no_groq)

    row = store.get_match(spar.match_id)
    assert row is not None and row.status == "failed"
    assert row.error is not None and "groq" in row.error


def test_a_spar_fails_cleanly_when_the_house_bot_is_gone(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))
    no_house = Config(SETTINGS, CONFIG.providers, {}, house_bot=None)

    run(blocking, spar.match_id, config=no_house)

    row = store.get_match(spar.match_id)
    assert row is not None and row.status == "failed"
    assert row.error is not None and "house" in row.error


def test_a_spar_whose_fighter_version_vanished_fails(
    database: str, config_file: object, encryption: None, sign_in: Any
) -> None:
    spar = Spar(sign_in("ada"))
    with store.connect() as conn:
        conn.execute("DELETE FROM fighter_versions")
    assert fighters.current_version(spar.fighter_id) is None

    run(blocking, spar.match_id)

    row = store.get_match(spar.match_id)
    assert row is not None and row.status == "failed"
