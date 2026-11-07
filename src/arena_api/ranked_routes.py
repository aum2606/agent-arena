from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException

from arena.config import load_config
from arena_api import fighters, store
from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.db import fighters_config_path
from arena_api.match_routes import MatchStatus, get_queue, queue_match
from arena_api.ratings import pick_opponent
from arena_api.store import Entrant, LeaderboardRow

router = APIRouter()


@router.post("/fighters/{fighter_id}/ranked", status_code=202)
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


@router.get("/leaderboard")
def leaderboard() -> list[LeaderboardRow]:
    return store.leaderboard()
