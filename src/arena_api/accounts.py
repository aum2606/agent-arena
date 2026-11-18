import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import psycopg.errors
from psycopg.types.json import Jsonb

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
        # Nothing else deletes an expired session, so signing in tidies up (D-078).
        conn.execute("DELETE FROM sessions WHERE expires_at < now()")
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


def end_all_sessions(user_id: int) -> None:
    """Sign the user out on every device."""
    with store.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def _without_player(log: dict[str, Any] | None, side: str) -> dict[str, Any] | None:
    """The stored battle log with one side's name and persona taken out of its header."""
    if log is None or side not in log.get("fighters", {}):
        return log
    gone = {**log["fighters"][side], "name": "deleted", "persona": "[removed]"}
    return {**log, "fighters": {**log["fighters"], side: gone}}


def delete_account(user_id: int) -> bool:
    """Erase the user, their fighters, saved keys and sessions (the database cascades) and their
    sparring matches. A ranked match stays, because the other player's rating and history came
    from it, but this user's name and persona are removed from it. False if a match of theirs is
    waiting or being played: it would still spend their key (D-078)."""
    with store.connect() as conn:
        busy = conn.execute(
            "SELECT 1 FROM matches WHERE status IN ('queued', 'running') "
            "AND (requested_by = %s OR opponent_owner = %s) LIMIT 1",
            (user_id, user_id),
        ).fetchone()
        if busy:
            return False
        conn.execute(
            "DELETE FROM matches WHERE mode = 'sparring' AND requested_by = %s", (user_id,)
        )
        ranked = conn.execute(
            "SELECT id, log, requested_by FROM matches WHERE mode = 'ranked' "
            "AND (requested_by = %s OR opponent_owner = %s)",
            (user_id, user_id),
        ).fetchall()
        for row in ranked:
            as_a = row["requested_by"] == user_id
            log = _without_player(row["log"], "a" if as_a else "b")
            sql = (
                "UPDATE matches SET fighter_a = 'deleted', log = %s WHERE id = %s"
                if as_a
                else "UPDATE matches SET fighter_b = 'deleted', log = %s WHERE id = %s"
            )
            conn.execute(sql, (Jsonb(log) if log is not None else None, row["id"]))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    return True
