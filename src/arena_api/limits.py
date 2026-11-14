from collections.abc import Awaitable, Callable
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends

from arena_api.accounts import User
from arena_api.auth import current_user
from arena_api.deps import get_queue
from arena_api.visitor_limits import count_request

# Per signed-in user: (requests allowed, window in seconds). Only routes that write or spend are
# limited here (D-050); the routes visitors can read have per-address limits (visitor_limits.py).
# Matches also have daily caps of their own (D-034, D-035, D-043).
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
        await count_request(redis, f"rate:{name}:{user.id}", name, allowed, window)

    return check
