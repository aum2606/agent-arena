from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from arena.config import ConfigError, load_config
from arena.moderation import check_text, has_hidden_characters
from arena_api import fighters, store
from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.db import fighters_config_path
from arena_api.deps import get_queue
from arena_api.fighters import FighterView
from arena_api.limits import rate_limit
from arena_api.match_routes import BUSY, MatchStatus, start_sparring, status_of
from arena_api.secret_box import encrypt
from arena_api.visitor_limits import visitor_limit

router = APIRouter(prefix="/fighters", dependencies=[Depends(visitor_limit("session"))])

MAX_FIGHTERS_PER_USER = 10
MAX_SPARS_PER_USER_PER_DAY = 5  # sparring spends the house bot's free-tier quota
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


def _visible(value: str) -> str:
    """Persona and model show in the other player's ranked replay: nothing may hide in them."""
    if has_hidden_characters(value):
        raise ValueError("must not contain invisible or control characters")
    return value


class NewFighter(BaseModel):
    name: str = Field(pattern=NAME)
    provider: str
    model: str = Field(min_length=1, max_length=100)
    persona: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(min_length=8, max_length=512, pattern=NO_SPACES)
    daily_match_cap: int = Field(DEFAULT_DAILY_CAP, ge=1, le=50)

    _no_hidden = field_validator("model", "persona")(_visible)


class RankedPool(BaseModel):
    enabled: bool


class NewVersion(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=100)
    persona: str = Field(min_length=1, max_length=2000)
    # Left out: keep the saved key.
    api_key: str | None = Field(None, min_length=8, max_length=512, pattern=NO_SPACES)
    daily_match_cap: int | None = Field(None, ge=1, le=50)

    _no_hidden = field_validator("model", "persona")(_visible)


def _check_provider(name: str) -> None:
    providers = load_config(fighters_config_path()).providers
    if name not in providers:
        known = ", ".join(providers)
        raise HTTPException(status_code=422, detail=f"unknown provider {name!r} (known: {known})")


def _check_terms(name: str | None, model: str, persona: str) -> None:
    """Refuse text with a term the deployer blocked (D-080); the message never repeats the term."""
    terms = load_config(fighters_config_path()).settings.blocked_terms
    for field, text in (("name", name), ("model", model), ("persona", persona)):
        if text and (reason := check_text(text, terms)):
            raise HTTPException(status_code=422, detail=f"the {field} {reason}")


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
    config = load_config(fighters_config_path())
    # The models the config already uses are the only ones known to work with that provider.
    used = [*config.fighters.values(), *config.panel]
    providers = [
        {
            "name": name,
            "models": list(dict.fromkeys(f.model for f in used if f.provider == name)),
            "key_url": provider.key_url,
        }
        for name, provider in config.providers.items()
    ]
    return {"providers": providers, "templates": PERSONA_TEMPLATES}


@router.post("", status_code=201, dependencies=[Depends(rate_limit("create_fighter"))])
def create(body: NewFighter, user: Annotated[User, Depends(current_user)]) -> FighterView:
    _check_provider(body.provider)
    _check_terms(body.name, body.model, body.persona)
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


@router.post(
    "/{fighter_id}/versions",
    status_code=201,
    dependencies=[Depends(rate_limit("new_version"))],
)
def new_version(
    fighter_id: int, body: NewVersion, user: Annotated[User, Depends(current_user)]
) -> FighterView:
    _mine(user, fighter_id)
    _check_provider(body.provider)
    _check_terms(None, body.model, body.persona)
    current = fighters.current_version(fighter_id)
    assert current is not None  # a fighter is created together with its first version
    if body.provider != current.provider and not body.api_key:
        # The saved key belongs to the old provider: it must not be sent to another one.
        raise HTTPException(
            status_code=422, detail="changing the provider needs a new API key for it"
        )
    stored = _encrypted(body.api_key) if body.api_key else current.api_key_encrypted
    hint = body.api_key[-4:] if body.api_key else current.key_hint
    fighters.add_version(
        fighter_id, body.provider, body.model, body.persona, stored, hint, body.daily_match_cap
    )
    return _mine(user, fighter_id)


@router.put("/{fighter_id}/ranked-pool", dependencies=[Depends(rate_limit("fighter_edit"))])
def ranked_pool(
    fighter_id: int, body: RankedPool, user: Annotated[User, Depends(current_user)]
) -> FighterView:
    """Let other players' ranked matches use this fighter (they spend its key), or stop them."""
    _mine(user, fighter_id)
    fighters.set_ranked_opt_in(fighter_id, body.enabled)
    return _mine(user, fighter_id)


@router.delete("/{fighter_id}", status_code=204, dependencies=[Depends(rate_limit("fighter_edit"))])
def delete(fighter_id: int, user: Annotated[User, Depends(current_user)]) -> None:
    """Erase the fighter and every key it stored; refused while one of its matches is waiting or
    being played."""
    _mine(user, fighter_id)
    if store.has_unfinished_matches(fighter_id):
        raise HTTPException(
            status_code=409,
            detail="a match of this fighter is waiting or running: try again after it",
        )
    fighters.delete(user.id, fighter_id)


@router.post("/{fighter_id}/spar", status_code=202, dependencies=[Depends(rate_limit("spar"))])
async def spar(
    fighter_id: int,
    user: Annotated[User, Depends(current_user)],
    queue: Annotated[ArqRedis, Depends(get_queue)],
) -> MatchStatus:
    """Queue a sparring match between this fighter's latest version and the house bot."""
    fighter = _mine(user, fighter_id)
    with store.try_lock(store.USER_LOCK, user.id) as got:
        if not got:
            raise HTTPException(status_code=429, detail=BUSY)
        return await _spar(fighter, user, queue)


async def _spar(fighter: FighterView, user: User, queue: ArqRedis) -> MatchStatus:
    fighter_id = fighter.id
    config = load_config(fighters_config_path())
    if config.house_bot is None:
        raise HTTPException(status_code=503, detail="no house bot is configured to spar against")
    if fighter.provider not in config.providers:
        raise HTTPException(
            status_code=422, detail=f"provider {fighter.provider!r} is not available any more"
        )
    if store.count_recent_for_fighter(fighter_id) >= fighter.daily_match_cap:
        raise HTTPException(status_code=429, detail="this fighter has reached its daily match cap")
    if store.count_recent_spars(user.id) >= MAX_SPARS_PER_USER_PER_DAY:
        raise HTTPException(status_code=429, detail="you have reached the daily sparring limit")
    return await start_sparring(
        queue,
        f"{user.handle}/{fighter.name}",
        config.house_bot,
        user.id,
        fighter_id,
        fighter.version,
    )


@router.get("/{fighter_id}/spars")
def spars(fighter_id: int, user: Annotated[User, Depends(current_user)]) -> list[MatchStatus]:
    _mine(user, fighter_id)
    return [status_of(row) for row in store.spars_for_fighter(fighter_id)]
