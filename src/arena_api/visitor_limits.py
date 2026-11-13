import ipaddress
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from arena_api.deps import get_queue

logger = logging.getLogger(__name__)

# Per visitor address, for the routes anyone can reach: (requests allowed, window in seconds). A
# page view makes at most one "read" request; the per-page session check and the health check
# are not counted (D-063).
VISITOR_RULES: dict[str, tuple[int, int]] = {
    "read": (60, 60),  # replays and the leaderboard
    "login": (20, 60),  # the GitHub sign-in round trip
}


async def count_request(redis: ArqRedis, key: str, name: str, allowed: int, window: int) -> None:
    """Count one request under `key`; past `allowed` in `window` seconds raise 429."""
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


def client_address(request: Request) -> str:
    """The visitor's address. The web server sits between visitors and this API, so the connection
    is always the web server: the deployer names, in CLIENT_IP_HEADER, a header their reverse proxy
    overwrites with the real address. Anything that is not exactly one address, or no setting at
    all, falls back to the connection, so a made-up header cannot buy a fresh allowance."""
    header = os.environ.get("CLIENT_IP_HEADER")
    if header:
        try:
            return str(ipaddress.ip_address(request.headers.get(header, "").strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def visitor_limit(name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: at most VISITOR_RULES[name] requests per address per window, else 429."""

    async def check(request: Request, redis: Annotated[ArqRedis, Depends(get_queue)]) -> None:
        allowed, window = VISITOR_RULES[name]
        await count_request(
            redis, f"rate:{name}:ip:{client_address(request)}", name, allowed, window
        )

    return check
