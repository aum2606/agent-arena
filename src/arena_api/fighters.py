from dataclasses import dataclass
from typing import Any

import psycopg.errors

from arena_api import store


class DuplicateFighter(Exception):
    pass


@dataclass(frozen=True)
class FighterView:
    """What the API shows of a fighter: its latest version, never the key."""

    id: int
    name: str
    version: int
    provider: str
    model: str
    persona: str
    key_hint: str
    verified: bool
    daily_match_cap: int


@dataclass(frozen=True)
class Version:
    """A stored version, including its encrypted key; only the server side ever holds this."""

    fighter_id: int
    version: int
    provider: str
    model: str
    persona: str
    api_key_encrypted: str
    key_hint: str


_VIEW_SQL = (
    "SELECT f.id, f.name, f.daily_match_cap, v.version, v.provider, v.model, v.persona, "
    "v.key_hint, v.verified_at IS NOT NULL AS verified FROM fighters f "
    "JOIN LATERAL (SELECT * FROM fighter_versions WHERE fighter_id = f.id "
    "ORDER BY version DESC LIMIT 1) v ON true WHERE f.owner_id = %s"
)


def count_for_owner(owner_id: int) -> int:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM fighters WHERE owner_id = %s", (owner_id,)
        ).fetchone()
    return int(row["n"]) if row else 0


def create_fighter(
    owner_id: int,
    name: str,
    daily_match_cap: int,
    provider: str,
    model: str,
    persona: str,
    api_key_encrypted: str,
    key_hint: str,
) -> int:
    """Create the fighter with its first version; DuplicateFighter if the owner has that name."""
    try:
        with store.connect() as conn:
            row = conn.execute(
                "INSERT INTO fighters (owner_id, name, daily_match_cap) VALUES (%s, %s, %s) "
                "RETURNING id",
                (owner_id, name, daily_match_cap),
            ).fetchone()
            assert row is not None
            conn.execute(
                "INSERT INTO fighter_versions (fighter_id, version, provider, model, persona, "
                "api_key_encrypted, key_hint) VALUES (%s, 1, %s, %s, %s, %s, %s)",
                (row["id"], provider, model, persona, api_key_encrypted, key_hint),
            )
    except psycopg.errors.UniqueViolation as exc:
        raise DuplicateFighter(name) from exc
    return int(row["id"])


def add_version(
    fighter_id: int,
    provider: str,
    model: str,
    persona: str,
    api_key_encrypted: str,
    key_hint: str,
    daily_match_cap: int | None,
) -> None:
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO fighter_versions (fighter_id, version, provider, model, persona, "
            "api_key_encrypted, key_hint) VALUES (%s, (SELECT COALESCE(MAX(version), 0) + 1 "
            "FROM fighter_versions WHERE fighter_id = %s), %s, %s, %s, %s, %s)",
            (fighter_id, fighter_id, provider, model, persona, api_key_encrypted, key_hint),
        )
        if daily_match_cap is not None:
            conn.execute(
                "UPDATE fighters SET daily_match_cap = %s WHERE id = %s",
                (daily_match_cap, fighter_id),
            )


def list_for_owner(owner_id: int) -> list[FighterView]:
    with store.connect() as conn:
        rows = conn.execute(_VIEW_SQL + " ORDER BY f.id", (owner_id,)).fetchall()
    return [FighterView(**row) for row in rows]


def get_for_owner(owner_id: int, fighter_id: int) -> FighterView | None:
    with store.connect() as conn:
        row = conn.execute(_VIEW_SQL + " AND f.id = %s", (owner_id, fighter_id)).fetchone()
    return FighterView(**row) if row else None


def _version_from(row: dict[str, Any] | None) -> Version | None:
    return Version(**row) if row else None


def current_version(fighter_id: int) -> Version | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT fighter_id, version, provider, model, persona, api_key_encrypted, key_hint "
            "FROM fighter_versions WHERE fighter_id = %s ORDER BY version DESC LIMIT 1",
            (fighter_id,),
        ).fetchone()
    return _version_from(row)
