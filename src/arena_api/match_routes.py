import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError

from arena.config import load_config
from arena_api import store
from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.db import fighters_config_path
from arena_api.visitor_limits import count_request, visitor_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/matches", dependencies=[Depends(visitor_limit("session"))])

BUDGET_KEY = "budget:server-matches"
BUSY = "another request of yours is still being handled: try again in a moment"

# Matches wait for the single worker and the free tiers make each one slow, so few may queue.
MAX_QUEUED = 5
# One user must not fill the only worker's queue (D-070).
MAX_QUEUED_PER_USER = 2


@dataclass(frozen=True)
class MatchStatus:
    id: str
    status: str  # queued, running, finished or failed
    fighter_a: str | None
    fighter_b: str | None
    error: str | None
    fighter_version: int | None
    rating_delta: float | None  # ranked, once finished: how the requester's rating moved


def status_of(row: store.MatchRow) -> MatchStatus:
    return MatchStatus(
        row.id,
        row.status,
        row.fighter_a,
        row.fighter_b,
        row.error,
        row.fighter_version,
        row.rating_delta_a,
    )


async def start_sparring(
    queue: ArqRedis, fighter_a: str, fighter_b: str, user_id: int, fighter_id: int, version: int
) -> MatchStatus:
    """Save a queued sparring match and hand it to the worker."""
    return await queue_match(
        queue,
        user_id,
        lambda match_id: store.create_match(
            match_id, fighter_a, fighter_b, "sparring", user_id, fighter_id, version
        ),
    )


async def queue_match(queue: ArqRedis, user_id: int, create: Callable[[str], None]) -> MatchStatus:
    """Save a queued match with `create` and hand it to the worker."""
    if store.count_queued() >= MAX_QUEUED:
        raise HTTPException(status_code=429, detail="too many matches are waiting; try again later")
    if store.count_unfinished_for_user(user_id) >= MAX_QUEUED_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"you already have {MAX_QUEUED_PER_USER} matches waiting or playing: "
            "wait for one to finish",
        )
    # Every match spends the server's own keys (house bot, review panel): one shared budget a day.
    await count_request(
        queue,
        BUDGET_KEY,
        "server_budget",
        load_config(fighters_config_path()).settings.server_matches_per_day,
        86_400,
        detail="today's shared free-tier model budget is used up; try again tomorrow",
    )
    match_id = f"m_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(2)}"
    create(match_id)
    try:
        await queue.enqueue_job("play_match", match_id)
    except (RedisError, OSError) as exc:
        logger.warning("could not queue match %s: %s", match_id, exc)
        store.mark_failed(match_id, "could not queue the match")
        raise HTTPException(status_code=503, detail="the match queue is not available") from exc
    row = store.get_match(match_id)
    assert row is not None
    return status_of(row)


# Declared before `/{match_id}`, which would otherwise take "mine" for a match id.
@router.get("/mine", dependencies=[Depends(visitor_limit("read"))])
def my_matches(user: Annotated[User, Depends(current_user)]) -> list[store.MyMatch]:
    return store.matches_for_user(user.id)


@router.get("/{match_id}")
def match_status(match_id: str, user: Annotated[User, Depends(current_user)]) -> MatchStatus:
    row = store.get_match(match_id)
    if row is None or row.requested_by != user.id:
        raise HTTPException(status_code=404, detail="match not found")
    return status_of(row)
