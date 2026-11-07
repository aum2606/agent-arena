import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, HTTPException
from redis.exceptions import RedisError

from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.match_routes import get_queue

logger = logging.getLogger(__name__)

# Per signed-in user: (requests allowed, window in seconds). Only routes that write or spend are
# limited; reading is not (D-050). Matches also have daily caps of their own (D-034, D-035, D-043).
RULES: dict[str, tuple[int, int]] = {
    "create_fighter": (20, 60),  # above the 10-fighter cap, so the cap message comes first
    "new_version": (100, 86_400),
    "spar": (10, 60),
    "ranked": (10, 60),
}


def rate_limit(name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: at most RULES[name] requests per user per window, else 429."""

    async def check(
        user: Annotated[User, Depends(current_user)],
        redis: Annotated[ArqRedis, Depends(get_queue)],
    ) -> None:
        allowed, window = RULES[name]
        key = f"rate:{name}:{user.id}"
        try:
            # SET with a lifetime first, so a counter can never outlive a crash between two calls.
            await redis.set(key, 0, ex=window, nx=True)
            used = await redis.incr(key)
            wait = await redis.ttl(key) if used > allowed else 0
        except (RedisError, OSError) as exc:
            # Fail open: with Redis down no match can be queued anyway, and the per-user caps hold.
            logger.warning("rate limit %r not checked, Redis failed: %s", name, exc)
            return
        if used > allowed:
            raise HTTPException(
                status_code=429,
                detail="too many requests; try again later",
                headers={"Retry-After": str(wait if wait > 0 else window)},
            )

    return check
