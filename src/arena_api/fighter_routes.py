from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arena.config import ConfigError, load_config
from arena_api import fighters
from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.db import fighters_config_path
from arena_api.fighters import FighterView
from arena_api.secret_box import encrypt

router = APIRouter(prefix="/fighters")

MAX_FIGHTERS_PER_USER = 10
DEFAULT_DAILY_CAP = 10  # matches per fighter per day; bounds what a fighter can spend
PERSONA_TEMPLATES = [
    {
        "name": "Aggressive",
        "persona": "An aggressive competitor. When attacking, pose the hardest problem you can "
        "still verify with certainty. When defending, answer fast and move on.",
    },
    {
        "name": "Defensive",
        "persona": "A defensive competitor. When defending, check every answer twice before "
        "giving it. When attacking, pose problems you are completely sure of.",
    },
    {
        "name": "Counter-puncher",
        "persona": "A counter-puncher. Defend carefully, and when attacking, build on the kind of "
        "problem that just beat you.",
    },
]
NAME = r"^[A-Za-z0-9_-]{1,32}$"
NO_SPACES = r"^\S+$"


class NewFighter(BaseModel):
    name: str = Field(pattern=NAME)
    provider: str
    model: str = Field(min_length=1, max_length=100)
    persona: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(min_length=8, max_length=512, pattern=NO_SPACES)
    daily_match_cap: int = Field(DEFAULT_DAILY_CAP, ge=1, le=50)


class NewVersion(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=100)
    persona: str = Field(min_length=1, max_length=2000)
    # Left out: keep the saved key.
    api_key: str | None = Field(None, min_length=8, max_length=512, pattern=NO_SPACES)
    daily_match_cap: int | None = Field(None, ge=1, le=50)


def _check_provider(name: str) -> None:
    providers = load_config(fighters_config_path()).providers
    if name not in providers:
        known = ", ".join(providers)
        raise HTTPException(status_code=422, detail=f"unknown provider {name!r} (known: {known})")


def _encrypted(api_key: str) -> str:
    try:
        return encrypt(api_key)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _mine(user: User, fighter_id: int) -> FighterView:
    found = fighters.get_for_owner(user.id, fighter_id)
    if found is None:
        raise HTTPException(status_code=404, detail="fighter not found")
    return found


@router.get("")
def list_mine(user: Annotated[User, Depends(current_user)]) -> list[FighterView]:
    return fighters.list_for_owner(user.id)


@router.get("/options")
def options(user: Annotated[User, Depends(current_user)]) -> dict[str, object]:
    providers = list(load_config(fighters_config_path()).providers)
    return {"providers": providers, "templates": PERSONA_TEMPLATES}


@router.post("", status_code=201)
def create(body: NewFighter, user: Annotated[User, Depends(current_user)]) -> FighterView:
    _check_provider(body.provider)
    if fighters.count_for_owner(user.id) >= MAX_FIGHTERS_PER_USER:
        raise HTTPException(status_code=409, detail="you have reached the fighter limit")
    try:
        fighter_id = fighters.create_fighter(
            user.id,
            body.name,
            body.daily_match_cap,
            body.provider,
            body.model,
            body.persona,
            _encrypted(body.api_key),
            body.api_key[-4:],
        )
    except fighters.DuplicateFighter as exc:
        raise HTTPException(
            status_code=409, detail="you already have a fighter with that name"
        ) from exc
    return _mine(user, fighter_id)


@router.get("/{fighter_id}")
def get_one(fighter_id: int, user: Annotated[User, Depends(current_user)]) -> FighterView:
    return _mine(user, fighter_id)


@router.post("/{fighter_id}/versions", status_code=201)
def new_version(
    fighter_id: int, body: NewVersion, user: Annotated[User, Depends(current_user)]
) -> FighterView:
    _mine(user, fighter_id)
    _check_provider(body.provider)
    current = fighters.current_version(fighter_id)
    assert current is not None  # a fighter is created together with its first version
    stored = _encrypted(body.api_key) if body.api_key else current.api_key_encrypted
    hint = body.api_key[-4:] if body.api_key else current.key_hint
    fighters.add_version(
        fighter_id, body.provider, body.model, body.persona, stored, hint, body.daily_match_cap
    )
    return _mine(user, fighter_id)
