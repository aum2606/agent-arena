from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from arena_api.db import database_url
from arena_api.ratings import START_RATING, Candidate, rate
from arena_api.replays import ReplaySummary


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


@dataclass(frozen=True)
class Entrant:
    """One side of a ranked match: a fighter's version, its owner and its display name."""

    fighter_id: int
    version: int
    owner_id: int
    name: str


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
    "opponent_id, opponent_version, opponent_owner, rating_delta_a"
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


def rating_of(fighter_id: int) -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT rating FROM ratings WHERE fighter_id = %s", (fighter_id,)
        ).fetchone()
    return float(row["rating"]) if row else START_RATING


def ranked_candidates(owner_id: int, providers: list[str]) -> list[Candidate]:
    """Other owners' fighters that can be paired now: their latest version has passed a spar, its
    provider is still configured, and the fighter is under its daily cap."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT f.id AS fighter_id, f.owner_id, COALESCE(r.rating, %s) AS rating, "
            "COALESCE(r.games, 0) AS games, v.version, u.handle || '/' || f.name AS name "
            "FROM fighters f JOIN users u ON u.id = f.owner_id "
            "JOIN LATERAL (SELECT * FROM fighter_versions WHERE fighter_id = f.id "
            "ORDER BY version DESC LIMIT 1) v ON true "
            "LEFT JOIN ratings r ON r.fighter_id = f.id "
            "WHERE f.owner_id <> %s AND v.verified_at IS NOT NULL AND v.provider = ANY(%s) "
            "AND (SELECT count(*) FROM matches m WHERE (m.fighter_id = f.id "
            "OR m.opponent_id = f.id) AND m.created_at > now() - interval '1 day') "
            "< f.daily_match_cap",
            (START_RATING, owner_id, providers),
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
