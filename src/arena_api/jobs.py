import asyncio
import logging
import random
from typing import Any

from arq.connections import RedisSettings

from arena.battle_log import BattleLog
from arena.config import Config, ConfigError, load_config
from arena.llm import LlmClient, LlmError
from arena.orchestrator import Complete, run_match
from arena_api import store
from arena_api.db import fighters_config_path, migrate, redis_url
from arena_api.replays import parse_replay

logger = logging.getLogger(__name__)

# A live match takes minutes when the free tiers rate-limit, so the job limit is generous.
JOB_TIMEOUT_S = 3600


def _play(
    config: Config, complete: Complete, match_id: str, names: tuple[str | None, str | None]
) -> dict[str, Any]:
    fighter_a, fighter_b = (config.fighters.get(name or "") for name in names)
    if fighter_a is None or fighter_b is None:
        raise ConfigError(f"fighters {names} are not both in the config any more")
    log = BattleLog(match_id)
    run_match(fighter_a, fighter_b, complete, config.settings, log, random.Random())
    return log.to_dict()


async def play_match(ctx: dict[str, Any], match_id: str) -> None:
    """Play one queued match and store its log. Provider and config errors fail the match."""
    row = store.get_match(match_id)
    if row is None or not store.mark_running(match_id):
        logger.warning("not playing %s: unknown or no longer queued", match_id)
        return
    try:
        log = await asyncio.to_thread(
            _play, ctx["config"], ctx["complete"], match_id, (row.fighter_a, row.fighter_b)
        )
    except (LlmError, ConfigError) as exc:
        store.mark_failed(match_id, str(exc))
        return
    except Exception as exc:
        store.mark_failed(match_id, f"unexpected error: {exc!r}")
        raise
    store.mark_finished(match_id, log, parse_replay(match_id, log).summary)


async def startup(ctx: dict[str, Any]) -> None:
    migrate()
    config = load_config(fighters_config_path())
    ctx["config"] = config
    ctx["complete"] = LlmClient(config.providers, config.settings).complete
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
