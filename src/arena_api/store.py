import os
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from arena_api.db import database_url
from arena_api.ratings import START_RATING, Candidate, rate
from arena_api.replays import ReplaySummary

# Two owners can rate each other this many times a day, so two accounts cannot trade wins (D-077).
MAX_PAIR_MATCHES_PER_DAY = 3


@dataclass(frozen=True)
class MatchRow:
    id: str
    status: str  # queued, running, finished or failed
    fighter_a: str | None
    fighter_b: str | None
    error: str | None
    mode: str = "sim"  # sim (imports, config fighters), sparring or ranked
    requested_by: int | None = None
    fighter_id: int | None = None
    fighter_version: int | None = None
    opponent_id: int | None = None  # ranked only: fighter B, pinned like fighter A
    opponent_version: int | None = None
    opponent_owner: int | None = None
    rating_delta_a: float | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class Entrant:
    """One side of a ranked match: a fighter's version, its owner and its display name."""

    fighter_id: int
    version: int
    owner_id: int
    name: str


@dataclass(frozen=True)
class RankedRow:
    """A ranked match as stored, from nobody's point of view yet."""

    id: str
    status: str
    fighter_id: int | None  # fighter A's id; the opponent is `opponent_id` in the table
    fighter_a: str | None
    fighter_b: str | None
    winner: str | None
    rating_delta_a: float | None
    error: str | None


@dataclass(frozen=True)
class MyMatch:
    """One line of a user's own match list: a spar or ranked match they asked for or joined."""

    id: str
    mode: str  # sparring or ranked
    status: str  # queued, running, finished or failed
    you: str  # "a" when you asked for it, "b" when your fighter was the ranked opponent
    name_a: str | None
    name_b: str | None
    winner: str | None  # all of these are None until it has finished
    hp_a: float | None
    hp_b: float | None
    turn_count: int | None
    ended_at: datetime | None


@dataclass(frozen=True)
class LeaderboardRow:
    handle: str
    name: str
    rating: float
    games: int
    wins: int
    draws: int
    losses: int
    form: str  # the last five results, newest first: W, D or L


_MATCH_COLUMNS = (
    "id, status, fighter_a, fighter_b, error, mode, requested_by, fighter_id, fighter_version, "
    "opponent_id, opponent_version, opponent_owner, rating_delta_a, ended_at"
)


# One bounded pool per database instead of a connection per call: a flood of cheap requests (each
# session check opens one) could use up Postgres's connections (D-070).
POOL_SIZE_ENV = "ARENA_DB_POOL"
DEFAULT_POOL_SIZE = 10
POOL_WAIT_S = 5.0  # how long a request waits for a free connection before the API says "busy"
_pools: dict[str, ConnectionPool[psycopg.Connection[dict[str, Any]]]] = {}
_pools_lock = threading.Lock()


def _pool() -> ConnectionPool[psycopg.Connection[dict[str, Any]]]:
    url = database_url()
    with _pools_lock:
        pool = _pools.get(url)
        if pool is None:
            pool = ConnectionPool(
                url,
                min_size=1,
                max_size=int(os.environ.get(POOL_SIZE_ENV, DEFAULT_POOL_SIZE)),
                kwargs={"row_factory": dict_row},
                open=True,
            )
            _pools[url] = pool
    return pool


def connect() -> AbstractContextManager[psycopg.Connection[dict[str, Any]]]:
    """A pooled connection that commits when its `with` block ends, or rolls back on an error."""
    return _pool().connection(timeout=POOL_WAIT_S)


def close_pools() -> None:
    with _pools_lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()


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


def create_ranked_match(match_id: str, a: Entrant, b: Entrant) -> None:
    """Save a queued ranked match; A is the requester, B the opponent chosen for them."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO matches (id, status, fighter_a, fighter_b, mode, requested_by, "
            "fighter_id, fighter_version, opponent_id, opponent_version, opponent_owner) "
            "VALUES (%s, 'queued', %s, %s, 'ranked', %s, %s, %s, %s, %s, %s)",
            (
                match_id,
                a.name,
                b.name,
                a.owner_id,
                a.fighter_id,
                a.version,
                b.fighter_id,
                b.version,
                b.owner_id,
            ),
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


def ranked_for_fighter(fighter_id: int, limit: int = 10) -> list[RankedRow]:
    """The fighter's latest ranked matches, as A or as B, newest first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, status, fighter_id, fighter_a, fighter_b, winner, rating_delta_a, error "
            "FROM matches WHERE mode = 'ranked' AND (fighter_id = %s OR opponent_id = %s) "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (fighter_id, fighter_id, limit),
        ).fetchall()
    return [RankedRow(**row) for row in rows]


def matches_for_user(user_id: int, limit: int = 20) -> list[MyMatch]:
    """The user's latest spars and ranked matches, newest first, as either side of it."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, mode, status, CASE WHEN requested_by = %s THEN 'a' ELSE 'b' END AS you, "
            "fighter_a AS name_a, fighter_b AS name_b, winner, hp_a, hp_b, turn_count, ended_at "
            "FROM matches WHERE mode IN ('sparring', 'ranked') "
            "AND (requested_by = %s OR opponent_owner = %s) "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (user_id, user_id, user_id, limit),
        ).fetchall()
    return [MyMatch(**row) for row in rows]


def count_queued() -> int:
    with connect() as conn:
        row = conn.execute("SELECT count(*) AS n FROM matches WHERE status = 'queued'").fetchone()
    return int(row["n"]) if row else 0


def count_recent_for_fighter(fighter_id: int) -> int:
    """Matches this fighter was queued for in the last day, whatever became of them. A ranked
    match spends both owners' keys, so it counts against both fighters' caps."""
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE (fighter_id = %s OR opponent_id = %s) "
            "AND created_at > now() - interval '1 day'",
            (fighter_id, fighter_id),
        ).fetchone()
    return int(row["n"]) if row else 0


def count_unfinished_for_user(user_id: int) -> int:
    """Matches this user asked for that are waiting or being played."""
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE requested_by = %s "
            "AND status IN ('queued', 'running')",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


USER_LOCK = 1  # the first key of an advisory lock held for one user's request


@contextmanager
def try_lock(kind: int, key: int) -> Iterator[bool]:
    """Hold a Postgres advisory lock while the block runs; False if someone holds it already.
    It never waits: the API serves requests on one event loop, and waiting would freeze it."""
    with connect() as conn:
        row = conn.execute("SELECT pg_try_advisory_lock(%s, %s) AS got", (kind, key)).fetchone()
        got = bool(row and row["got"])
        try:
            yield got
        finally:
            if got:
                conn.execute("SELECT pg_advisory_unlock(%s, %s)", (kind, key))


def has_unfinished_matches(fighter_id: int) -> bool:
    """A match of this fighter is waiting or being played, as either side."""
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM matches WHERE (fighter_id = %s OR opponent_id = %s) "
            "AND status IN ('queued', 'running') LIMIT 1",
            (fighter_id, fighter_id),
        ).fetchone()
    return row is not None


def count_recent_spars(user_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE requested_by = %s AND mode = 'sparring' "
            "AND created_at > now() - interval '1 day'",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def count_recent_ranked(user_id: int) -> int:
    """Ranked matches this user asked for in the last day, over all their fighters."""
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM matches WHERE requested_by = %s AND mode = 'ranked' "
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


_FINISH = (
    "UPDATE matches SET status = 'finished', log = %s, winner = %s, reason = %s, "
    "hp_a = %s, hp_b = %s, turn_count = %s, ended_at = now() WHERE id = %s"
)


def _finish_values(match_id: str, log: dict[str, Any], summary: ReplaySummary) -> tuple[Any, ...]:
    return (
        Jsonb(log),
        summary.winner,
        summary.reason,
        summary.hp_a,
        summary.hp_b,
        summary.turn_count,
        match_id,
    )


def mark_finished(match_id: str, log: dict[str, Any], summary: ReplaySummary) -> None:
    with connect() as conn:
        conn.execute(_FINISH, _finish_values(match_id, log, summary))


def finish_ranked(match_id: str, log: dict[str, Any], summary: ReplaySummary) -> bool:
    """Store a ranked result and rate both fighters in one transaction. False if the match was
    not running, so a repeat call cannot rate it twice."""
    with connect() as conn:
        done = conn.execute(
            _FINISH + " AND status = 'running' RETURNING fighter_id, opponent_id",
            _finish_values(match_id, log, summary),
        ).fetchone()
        if done is None:
            return False
        a, b = done["fighter_id"], done["opponent_id"]
        if a is None or b is None:  # a fighter was removed while the match played
            return True
        for fighter_id in (a, b):
            conn.execute(
                "INSERT INTO ratings (fighter_id, rating) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (fighter_id, START_RATING),
            )
        locked = {
            row["fighter_id"]: row["rating"]
            for row in conn.execute(
                "SELECT fighter_id, rating FROM ratings WHERE fighter_id IN (%s, %s) "
                "ORDER BY fighter_id FOR UPDATE",
                (a, b),
            )
        }
        score_a = {"a": 1.0, "b": 0.0, None: 0.5}[summary.winner]
        new_a, new_b = rate(locked[a], locked[b], score_a)
        for fighter_id, rating, score in ((a, new_a, score_a), (b, new_b, 1 - score_a)):
            conn.execute(
                "UPDATE ratings SET rating = %s, games = games + 1, wins = wins + %s, "
                "draws = draws + %s, losses = losses + %s, updated_at = now() "
                "WHERE fighter_id = %s",
                (rating, int(score == 1), int(score == 0.5), int(score == 0), fighter_id),
            )
        conn.execute(
            "UPDATE matches SET rating_delta_a = %s WHERE id = %s", (new_a - locked[a], match_id)
        )
    return True


def mark_failed(match_id: str, error: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE matches SET status = 'failed', error = %s, ended_at = now() "
            "WHERE id = %s AND status <> 'finished'",  # a late error never undoes a finished match
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
            "fighter_b AS name_b, mode, ended_at FROM matches "
            "WHERE status = 'finished' AND mode = 'sim' ORDER BY id"
        ).fetchall()
    return [ReplaySummary(**row) for row in rows]


def get_log(match_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT log FROM matches WHERE id = %s AND status = 'finished'", (match_id,)
        ).fetchone()
    return row["log"] if row else None


def rating_of(fighter_id: int) -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT rating FROM ratings WHERE fighter_id = %s", (fighter_id,)
        ).fetchone()
    return float(row["rating"]) if row else START_RATING


def ranked_candidates(owner_id: int, providers: list[str]) -> list[Candidate]:
    """Other owners' fighters that can be paired now: their latest version has passed a spar, its
    provider is still configured, and the fighter is under its daily cap. Only fighters whose
    owner opted in are paired, because the match spends their key (D-070)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT f.id AS fighter_id, f.owner_id, COALESCE(r.rating, %s) AS rating, "
            "COALESCE(r.games, 0) AS games, v.version, u.handle || '/' || f.name AS name "
            "FROM fighters f JOIN users u ON u.id = f.owner_id "
            "JOIN LATERAL (SELECT * FROM fighter_versions WHERE fighter_id = f.id "
            "ORDER BY version DESC LIMIT 1) v ON true "
            "LEFT JOIN ratings r ON r.fighter_id = f.id "
            "WHERE f.owner_id <> %s AND f.ranked_opt_in AND v.verified_at IS NOT NULL "
            "AND v.provider = ANY(%s) "
            "AND (SELECT count(*) FROM matches m WHERE (m.fighter_id = f.id "
            "OR m.opponent_id = f.id) AND m.created_at > now() - interval '1 day') "
            "< f.daily_match_cap "
            "AND (SELECT count(*) FROM matches p WHERE p.mode = 'ranked' "
            "AND p.created_at > now() - interval '1 day' "
            "AND ((p.requested_by = %s AND p.opponent_owner = f.owner_id) "
            "OR (p.requested_by = f.owner_id AND p.opponent_owner = %s))) < %s",
            (START_RATING, owner_id, providers, owner_id, owner_id, MAX_PAIR_MATCHES_PER_DAY),
        ).fetchall()
    return [Candidate(**row) for row in rows]


def leaderboard() -> list[LeaderboardRow]:
    """Every fighter with a ranked game, best rating first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT u.handle, f.name, r.rating, r.games, r.wins, r.draws, r.losses, "
            "COALESCE(form.results, '') AS form FROM ratings r "
            "JOIN fighters f ON f.id = r.fighter_id JOIN users u ON u.id = f.owner_id "
            "LEFT JOIN LATERAL (SELECT string_agg(res, '' ORDER BY ended_at DESC) AS results "
            "FROM (SELECT ended_at, CASE WHEN m.winner IS NULL THEN 'D' "
            "WHEN (m.winner = 'a') = (m.fighter_id = f.id) THEN 'W' ELSE 'L' END AS res "
            "FROM matches m WHERE m.mode = 'ranked' AND m.status = 'finished' "
            "AND (m.fighter_id = f.id OR m.opponent_id = f.id) "
            "ORDER BY ended_at DESC LIMIT 5) last) form ON true "
            "ORDER BY r.rating DESC, r.games DESC, f.id"
        ).fetchall()
    return [LeaderboardRow(**row) for row in rows]
