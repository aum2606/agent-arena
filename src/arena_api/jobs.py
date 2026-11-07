import asyncio
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arq.connections import RedisSettings

from arena.battle_log import BattleLog
from arena.config import Config, ConfigError, load_config
from arena.damage import MAX_TURNS
from arena.llm import Complete, LlmClient, LlmError
from arena.models import Fighter
from arena.orchestrator import run_match
from arena_api import fighters, store
from arena_api.db import fighters_config_path, migrate, redis_url
from arena_api.replays import parse_replay
from arena_api.secret_box import decrypt

logger = logging.getLogger(__name__)

# A live match takes minutes when the free tiers rate-limit, so the job limit is generous.
JOB_TIMEOUT_S = 3600
# The spec's "3 unranked rounds" (a round is a turn here, D-006): half a ranked match, so a spar
# costs the user's key and the house bot's free-tier quota less.
SPARRING_TURNS = 3
# Events that show a model actually replied (a timed-out call leaves no such event).
_REPLIED = ("attack_verified", "attack_retry", "defend_result")


@dataclass(frozen=True)
class Players:
    a: Fighter
    b: Fighter
    keys: dict[str, str]  # fighter name -> that fighter's own decrypted key
    max_turns: int


def _user_fighter(
    config: Config, name: str | None, fighter_id: int | None, number: int | None
) -> tuple[Fighter, str]:
    """A user's fighter as pinned in the match (not its latest version) and its decrypted key."""
    version = (
        fighters.version(fighter_id, number)
        if fighter_id is not None and number is not None
        else None
    )
    if version is None:
        raise ConfigError("the fighter version for this match no longer exists")
    if version.provider not in config.providers:
        raise ConfigError(f"provider {version.provider!r} is not in the config any more")
    fighter = Fighter(name or "", version.provider, version.model, version.persona)
    return fighter, decrypt(version.api_key_encrypted)


def _players(config: Config, row: store.MatchRow) -> Players:
    if row.mode == "sparring":
        mine, key = _user_fighter(config, row.fighter_a, row.fighter_id, row.fighter_version)
        house = config.fighters.get(config.house_bot or "")
        if house is None:
            raise ConfigError("no house bot is configured to spar against")
        return Players(mine, house, {mine.name: key}, SPARRING_TURNS)
    if row.mode == "ranked":
        mine, mine_key = _user_fighter(config, row.fighter_a, row.fighter_id, row.fighter_version)
        theirs, their_key = _user_fighter(
            config, row.fighter_b, row.opponent_id, row.opponent_version
        )
        return Players(mine, theirs, {mine.name: mine_key, theirs.name: their_key}, MAX_TURNS)
    a, b = (config.fighters.get(name or "") for name in (row.fighter_a, row.fighter_b))
    if a is None or b is None:
        raise ConfigError(
            f"fighters {row.fighter_a!r} and {row.fighter_b!r} are not both configured"
        )
    return Players(a, b, {}, MAX_TURNS)


def _play(config: Config, complete: Complete, match_id: str, players: Players) -> dict[str, Any]:
    log = BattleLog(match_id)
    run_match(
        players.a,
        players.b,
        complete,
        config.settings,
        log,
        random.Random(),
        max_turns=players.max_turns,
    )
    return log.to_dict()


def _scrub(text: str, keys: Mapping[str, str]) -> str:
    """Provider errors can echo the key they rejected; never store or show one."""
    for key in keys.values():
        text = text.replace(key, "[key]")
    return text


def _replied(log: dict[str, Any], side: str) -> bool:
    return any(
        event["type"] in _REPLIED and event.get("actor") == side
        for turn in log["turns"]
        for event in turn["events"]
    )


async def play_match(ctx: dict[str, Any], match_id: str) -> None:
    """Play one queued match and store its log. Provider and config errors fail the match."""
    row = store.get_match(match_id)
    if row is None or not store.mark_running(match_id):
        logger.warning("not playing %s: unknown or no longer queued", match_id)
        return
    keys: Mapping[str, str] = {}
    try:
        players = _players(ctx["config"], row)
        keys = players.keys
        log = await asyncio.to_thread(
            _play, ctx["config"], ctx["complete_with"](keys), match_id, players
        )
    except (LlmError, ConfigError) as exc:
        store.mark_failed(match_id, _scrub(str(exc), keys))
        return
    except Exception as exc:
        store.mark_failed(match_id, _scrub(f"unexpected error: {exc!r}", keys))
        raise
    summary = parse_replay(match_id, log).summary
    if row.mode == "ranked":
        store.finish_ranked(match_id, log, summary)
    else:
        store.mark_finished(match_id, log, summary)
    # A spar proves the key and model work when the fighter replied at least once.
    if row.mode == "sparring" and _replied(log, "a"):
        assert row.fighter_id is not None and row.fighter_version is not None
        fighters.mark_verified(row.fighter_id, row.fighter_version)


async def startup(ctx: dict[str, Any]) -> None:
    migrate()
    config = load_config(fighters_config_path())
    ctx["config"] = config
    # One client per match, so a user's key lives only as long as that match.
    ctx["complete_with"] = lambda keys: (
        LlmClient(config.providers, config.settings, keys=keys).complete
    )
    stale = store.fail_stale_running()
    if stale:
        logger.warning("marked %d match(es) left running by a dead worker as failed", stale)


class WorkerSettings:
    """Run with `arq arena_api.jobs.WorkerSettings`. One match at a time, never retried: a retry
    would play (and pay for) the match twice."""

    functions = [play_match]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(redis_url())
    max_jobs = 1
    max_tries = 1
    job_timeout = JOB_TIMEOUT_S
