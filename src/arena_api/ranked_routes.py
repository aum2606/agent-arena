from dataclasses import dataclass
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException

from arena.config import load_config
from arena_api import fighters, store
from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.db import fighters_config_path
from arena_api.limits import rate_limit
from arena_api.match_routes import MatchStatus, get_queue, queue_match
from arena_api.ratings import pick_opponent
from arena_api.store import Entrant, LeaderboardRow, RankedRow

router = APIRouter()


@router.post(
    "/fighters/{fighter_id}/ranked",
    status_code=202,
    dependencies=[Depends(rate_limit("ranked"))],
)
async def enter_ranked(
    fighter_id: int,
    user: Annotated[User, Depends(current_user)],
    queue: Annotated[ArqRedis, Depends(get_queue)],
) -> MatchStatus:
    """Queue a ranked match: this fighter's latest version against the closest-rated fighter of
    another owner. Both owners' keys play it."""
    fighter = fighters.get_for_owner(user.id, fighter_id)
    if fighter is None:
        raise HTTPException(status_code=404, detail="fighter not found")
    if not fighter.verified:
        raise HTTPException(
            status_code=409, detail="spar with this fighter first: ranked play needs a working key"
        )
    providers = list(load_config(fighters_config_path()).providers)
    if fighter.provider not in providers:
        raise HTTPException(
            status_code=422, detail=f"provider {fighter.provider!r} is not available any more"
        )
    if store.count_recent_for_fighter(fighter_id) >= fighter.daily_match_cap:
        raise HTTPException(status_code=429, detail="this fighter has reached its daily match cap")
    opponent = pick_opponent(
        user.id, store.rating_of(fighter_id), store.ranked_candidates(user.id, providers)
    )
    if opponent is None:
        raise HTTPException(
            status_code=409, detail="no other fighter is ready for a ranked match yet"
        )
    mine = Entrant(fighter.id, fighter.version, user.id, f"{user.handle}/{fighter.name}")
    theirs = Entrant(opponent.fighter_id, opponent.version, opponent.owner_id, opponent.name)
    return await queue_match(
        queue, lambda match_id: store.create_ranked_match(match_id, mine, theirs)
    )


@dataclass(frozen=True)
class RankedEntry:
    """One ranked match as the fighter's owner sees it: from that fighter's side."""

    id: str
    status: str  # queued, running, finished or failed
    opponent: str | None
    result: str | None  # W, D or L, once finished
    rating_delta: float | None  # this fighter's rating change, once finished
    error: str | None


def _entry(row: RankedRow, fighter_id: int) -> RankedEntry:
    is_a = row.fighter_id == fighter_id
    finished = row.status == "finished"
    result = None
    if finished:
        result = "D" if row.winner is None else "W" if (row.winner == "a") == is_a else "L"
    return RankedEntry(
        row.id,
        row.status,
        row.fighter_b if is_a else row.fighter_a,
        result,
        _delta(row, is_a),
        row.error,
    )


def _delta(row: RankedRow, is_a: bool) -> float | None:
    if row.status != "finished" or row.rating_delta_a is None:
        return None
    return row.rating_delta_a if is_a else 0.0 - row.rating_delta_a  # never -0.0 for a draw


@router.get("/fighters/{fighter_id}/ranked")
def ranked_history(
    fighter_id: int, user: Annotated[User, Depends(current_user)]
) -> list[RankedEntry]:
    """The fighter's latest ranked matches; only its owner may read them."""
    if fighters.get_for_owner(user.id, fighter_id) is None:
        raise HTTPException(status_code=404, detail="fighter not found")
    return [_entry(row, fighter_id) for row in store.ranked_for_fighter(fighter_id)]


@router.get("/leaderboard")
def leaderboard() -> list[LeaderboardRow]:
    return store.leaderboard()
