from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from arena_api.db import database_url
from arena_api.replays import ReplaySummary


@dataclass(frozen=True)
class MatchRow:
    id: str
    status: str  # queued, running, finished or failed
    fighter_a: str | None
    fighter_b: str | None
    error: str | None
    mode: str = "sim"  # sim (imports, config fighters) or sparring
    requested_by: int | None = None
    fighter_id: int | None = None
    fighter_version: int | None = None


_MATCH_COLUMNS = (
    "id, status, fighter_a, fighter_b, error, mode, requested_by, fighter_id, fighter_version"
)


def connect() -> psycopg.Connection[dict[str, Any]]:
    """A connection that commits when its `with` block ends."""
    return psycopg.connect(database_url(), row_factory=dict_row)


def create_match(
    match_id: str,
    fighter_a: str,
    fighter_b: str,
    mode: str = "sim",
    requested_by: int | None = None,
    fighter_id: int | None = None,
    fighter_version: int | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO matches (id, status, fighter_a, fighter_b, mode, requested_by, "
            "fighter_id, fighter_version) VALUES (%s, 'queued', %s, %s, %s, %s, %s, %s)",
            (match_id, fighter_a, fighter_b, mode, requested_by, fighter_id, fighter_version),
        )


def get_match(match_id: str) -> MatchRow | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {_MATCH_COLUMNS} FROM matches WHERE id = %s",
            (match_id,),
        ).fetchone()
    return MatchRow(**row) if row else None


def spars_for_fighter(fighter_id: int, limit: int = 10) -> list[MatchRow]:
    """The fighter's latest sparring matches, newest first."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {_MATCH_COLUMNS} FROM matches WHERE fighter_id = %s AND mode = 'sparring' "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (fighter_id, limit),
        ).fetchall()
    return [MatchRow(**row) for row in rows]


def count_queued() -> int:
    with connect() as conn:
        row = conn.execute("SELECT count(*) AS n FROM matches WHERE status = 'queued'").fetchone()
    return int(row["n"]) if row else 0


def count_recent_for_fighter(fighter_id: int) -> int:
    """Matches this fighter was queued for in the last day, whatever became of them."""
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE fighter_id = %s "
            "AND created_at > now() - interval '1 day'",
            (fighter_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def count_recent_spars(user_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE requested_by = %s AND mode = 'sparring' "
            "AND created_at > now() - interval '1 day'",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def mark_running(match_id: str) -> bool:
    """True if this call moved the match from queued to running (so only one worker plays it)."""
    with connect() as conn:
        done = conn.execute(
            "UPDATE matches SET status = 'running', started_at = now() "
            "WHERE id = %s AND status = 'queued'",
            (match_id,),
        )
    return done.rowcount == 1


def mark_finished(match_id: str, log: dict[str, Any], summary: ReplaySummary) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE matches SET status = 'finished', log = %s, winner = %s, reason = %s, "
            "hp_a = %s, hp_b = %s, turn_count = %s, ended_at = now() WHERE id = %s",
            (
                Jsonb(log),
                summary.winner,
                summary.reason,
                summary.hp_a,
                summary.hp_b,
                summary.turn_count,
                match_id,
            ),
        )


def mark_failed(match_id: str, error: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE matches SET status = 'failed', error = %s, ended_at = now() WHERE id = %s",
            (error, match_id),
        )


def fail_stale_running() -> int:
    """Fail matches a dead worker left running; called when a worker starts."""
    with connect() as conn:
        done = conn.execute(
            "UPDATE matches SET status = 'failed', ended_at = now(), "
            "error = 'the worker stopped while this match was running' WHERE status = 'running'"
        )
    return done.rowcount


def insert_finished(match_id: str, log: dict[str, Any], summary: ReplaySummary) -> bool:
    """Add an already-played match (an imported log). False if the id is taken."""
    with connect() as conn:
        done = conn.execute(
            "INSERT INTO matches (id, status, fighter_a, fighter_b, winner, reason, hp_a, hp_b, "
            "turn_count, log, started_at, ended_at) "
            "VALUES (%s, 'finished', %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
            "ON CONFLICT (id) DO NOTHING",
            (
                match_id,
                summary.name_a,
                summary.name_b,
                summary.winner,
                summary.reason,
                summary.hp_a,
                summary.hp_b,
                summary.turn_count,
                Jsonb(log),
            ),
        )
    return done.rowcount == 1


def list_finished() -> list[ReplaySummary]:
    """The public replay list: sparring matches are private to their owner and not in it."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, winner, reason, hp_a, hp_b, turn_count, fighter_a AS name_a, "
            "fighter_b AS name_b FROM matches WHERE status = 'finished' AND mode = 'sim' "
            "ORDER BY id"
        ).fetchall()
    return [ReplaySummary(**row) for row in rows]


def get_log(match_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT log FROM matches WHERE id = %s AND status = 'finished'", (match_id,)
        ).fetchone()
    return row["log"] if row else None
