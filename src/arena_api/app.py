import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from redis.exceptions import RedisError

from arena.config import load_config
from arena_api import store
from arena_api.db import fighters_config_path, migrate, redis_url
from arena_api.replays import VALID_ID, Replay, ReplayError, ReplaySummary, parse_replay

# Until sign-in exists (slice 6) anyone who can reach the API can spend the provider keys, so only
# a few matches may wait at once.
MAX_QUEUED = 5


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    migrate()
    app.state.queue = await create_pool(RedisSettings.from_dsn(redis_url()))
    yield
    await app.state.queue.aclose()


app = FastAPI(title="Agent Arena", lifespan=lifespan)


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.queue
    return queue


class NewMatch(BaseModel):
    fighter_a: str
    fighter_b: str


@dataclass(frozen=True)
class MatchStatus:
    id: str
    status: str
    fighter_a: str | None
    fighter_b: str | None
    error: str | None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/replays")
def replays() -> list[ReplaySummary]:
    return store.list_finished()


@app.get("/replays/{replay_id}")
def replay(replay_id: str) -> Replay:
    log = store.get_log(replay_id) if VALID_ID.fullmatch(replay_id) else None
    if log is None:
        raise HTTPException(status_code=404, detail="replay not found")
    try:
        return parse_replay(replay_id, log)
    except ReplayError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/matches", status_code=202)
async def start_match(
    body: NewMatch, queue: Annotated[ArqRedis, Depends(get_queue)]
) -> MatchStatus:
    fighters = load_config(fighters_config_path()).fighters
    unknown = [n for n in (body.fighter_a, body.fighter_b) if n not in fighters]
    if unknown or body.fighter_a == body.fighter_b:
        known = ", ".join(fighters)
        detail = (
            f"unknown fighter {unknown[0]!r} (known: {known})"
            if unknown
            else "pick two different fighters"
        )
        raise HTTPException(status_code=422, detail=detail)
    if store.count_queued() >= MAX_QUEUED:
        raise HTTPException(status_code=429, detail="too many matches are waiting; try again later")

    match_id = f"m_{datetime.now(UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(2)}"
    store.create_match(match_id, body.fighter_a, body.fighter_b)
    try:
        await queue.enqueue_job("play_match", match_id)
    except (RedisError, OSError) as exc:
        store.mark_failed(match_id, f"could not queue the match: {exc}")
        raise HTTPException(status_code=503, detail="the match queue is not available") from exc
    return MatchStatus(match_id, "queued", body.fighter_a, body.fighter_b, None)


@app.get("/matches/{match_id}")
def match_status(match_id: str) -> MatchStatus:
    row = store.get_match(match_id)
    if row is None:
        raise HTTPException(status_code=404, detail="match not found")
    return MatchStatus(row.id, row.status, row.fighter_a, row.fighter_b, row.error)
