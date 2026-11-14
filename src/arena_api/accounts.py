import hashlib
import secrets
from dataclasses import dataclass

import psycopg.errors

from arena_api import store

SESSION_DAYS = 14
MAX_HANDLE_TRIES = 50  # "alice", "alice-2", ... before giving up


@dataclass(frozen=True)
class User:
    id: int
    handle: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def upsert_user(provider: str, provider_user_id: str, handle: str) -> User:
    """The user behind this provider account; their handle follows the provider's current one.
    Handles are unique across providers, so a taken one gets a numeric suffix ("alice-2") rather
    than locking the user out of signing in (D-070)."""
    for attempt in range(1, MAX_HANDLE_TRIES + 1):
        wanted = handle if attempt == 1 else f"{handle}-{attempt}"
        try:
            with store.connect() as conn:
                row = conn.execute(
                    "INSERT INTO users (provider, provider_user_id, handle) VALUES (%s, %s, %s) "
                    "ON CONFLICT (provider, provider_user_id) "
                    "DO UPDATE SET handle = EXCLUDED.handle RETURNING id, handle",
                    (provider, provider_user_id, wanted),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            continue  # the handle (the only other unique column) belongs to someone else
        assert row is not None
        return User(**row)
    raise RuntimeError(f"no free handle near {handle!r}")


def create_session(user_id: int) -> str:
    """Start a session and return its token, which only the browser's cookie ever holds."""
    token = secrets.token_urlsafe(32)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, now() + make_interval(days => %s))",
            (_hash(token), user_id, SESSION_DAYS),
        )
    return token


def user_for_token(token: str) -> User | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.handle FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (_hash(token),),
        ).fetchone()
    return User(**row) if row else None


def end_session(token: str) -> None:
    with store.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash(token),))
