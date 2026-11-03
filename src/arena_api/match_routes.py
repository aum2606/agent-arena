import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request
from redis.exceptions import RedisError

from arena_api import store
from arena_api.accounts import User
from arena_api.auth import current_user

router = APIRouter(prefix="/matches")

# Matches wait for the single worker and the free tiers make each one slow, so few may queue.
MAX_QUEUED = 5


@dataclass(frozen=True)
class MatchStatus:
    id: str
    status: str  # queued, running, finished or failed
    fighter_a: str | None
    fighter_b: str | None
    error: str | None
    fighter_version: int | None


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.queue
    return queue


def status_of(row: store.MatchRow) -> MatchStatus:
    return MatchStatus(
        row.id, row.status, row.fighter_a, row.fighter_b, row.error, row.fighter_version
    )


async def start_sparring(
    queue: ArqRedis, fighter_a: str, fighter_b: str, user_id: int, fighter_id: int, version: int
) -> MatchStatus:
    """Save a queued sparring match and hand it to the worker."""
    if store.count_queued() >= MAX_QUEUED:
        raise HTTPException(status_code=429, detail="too many matches are waiting; try again later")
    match_id = f"m_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(2)}"
    store.create_match(match_id, fighter_a, fighter_b, "sparring", user_id, fighter_id, version)
    try:
        await queue.enqueue_job("play_match", match_id)
    except (RedisError, OSError) as exc:
        store.mark_failed(match_id, f"could not queue the match: {exc}")
        raise HTTPException(status_code=503, detail="the match queue is not available") from exc
    row = store.get_match(match_id)
    assert row is not None
    return status_of(row)


@router.get("/{match_id}")
def match_status(match_id: str, user: Annotated[User, Depends(current_user)]) -> MatchStatus:
    row = store.get_match(match_id)
    if row is None or row.requested_by != user.id:
        raise HTTPException(status_code=404, detail="match not found")
    return status_of(row)
