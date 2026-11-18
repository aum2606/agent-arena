import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Annotated

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from arena_api import store
from arena_api.accounts import User
from arena_api.auth import optional_user
from arena_api.auth import router as auth_router
from arena_api.db import migrate, redis_url
from arena_api.fighter_routes import router as fighter_router
from arena_api.guards import add_guards
from arena_api.match_routes import router as match_router
from arena_api.ranked_routes import router as ranked_router
from arena_api.replays import VALID_ID, Replay, ReplayError, ReplaySummary, parse_replay
from arena_api.secret_box import check_secret
from arena_api.visitor_limits import visitor_limit

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_secret()
    migrate()
    app.state.queue = await create_pool(RedisSettings.from_dsn(redis_url()))
    yield
    await app.state.queue.aclose()
    store.close_pools()


# No docs pages: they load scripts from a CDN on the app's own origin (D-068).
app = FastAPI(
    title="Agent Arena", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
)
add_guards(app)


@app.exception_handler(PoolTimeout)
def busy(request: Request, exc: PoolTimeout) -> JSONResponse:
    """Every database connection is in use: say so, and let the client try again."""
    return JSONResponse(
        {"detail": "the server is busy; try again in a moment"},
        status_code=503,
        headers={"Retry-After": "5"},
    )


app.include_router(auth_router)
app.include_router(fighter_router)
app.include_router(match_router)
app.include_router(ranked_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/replays", dependencies=[Depends(visitor_limit("read"))])
def replays() -> list[ReplaySummary]:
    return store.list_finished()


@app.get("/replays/{replay_id}", dependencies=[Depends(visitor_limit("read"))])
def replay(replay_id: str, viewer: Annotated[User | None, Depends(optional_user)]) -> Replay:
    row = store.get_match(replay_id) if VALID_ID.fullmatch(replay_id) else None
    # Sparring and ranked replays show a user's persona, so only the match's owners may open them.
    hidden = (
        row is not None
        and row.mode != "sim"
        and (viewer is None or viewer.id not in (row.requested_by, row.opponent_owner))
    )
    log = store.get_log(replay_id) if row is not None and not hidden else None
    if log is None:
        raise HTTPException(status_code=404, detail="replay not found")
    try:
        parsed = parse_replay(replay_id, log)
    except ReplayError as exc:
        logger.warning("replay %s cannot be shown: %s", replay_id, exc)
        raise HTTPException(status_code=500, detail="this replay cannot be shown") from exc
    assert row is not None  # a log is only found for an existing match
    # The log does not say how the match came about or when it ended: the match row does.
    summary = replace(parsed.summary, mode=row.mode, ended_at=row.ended_at)
    return replace(parsed, summary=summary)
