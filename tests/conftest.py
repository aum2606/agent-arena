import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from arena_api.db import migrate

# The compose Postgres with its local-only default password (D-028). Override to test elsewhere.
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://arena:arena-dev@127.0.0.1:5442/postgres"
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh, migrated database on the compose Postgres; skips the test if it is not running."""
    name = f"arena_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not reachable ({exc}); run `docker compose up -d postgres`")
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        url = make_conninfo(ADMIN_URL, dbname=name)
        monkeypatch.setenv("DATABASE_URL", url)
        migrate()
        try:
            yield url
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def sample_log() -> Callable[..., dict[str, Any]]:
    """A one-turn schema 2 battle log: alice attacks, bob blocks, alice wins on a decision."""

    def make(a: str = "alice", b: str = "bob") -> dict[str, Any]:
        def fighter(name: str) -> dict[str, str]:
            return {"name": name, "provider": "p", "model": "m", "persona": "persona"}

        events = [
            {"t": 0, "type": "attack_start", "actor": "a"},
            {"t": 5, "type": "attack_verified", "actor": "a", "problem": "6 * 7?", "answer": "42",
             "code": "print(42)"},
            {"t": 5, "type": "defend_start", "actor": "b"},
            {"t": 9, "type": "defend_result", "actor": "b", "score": 1.0, "answer": "42"},
            {"t": 9, "type": "block", "actor": "b"},
            {"t": 9, "type": "hp", "a": 100.0, "b": 100.0},
            {"t": 9, "type": "match_end", "winner": None, "reason": "decision", "turns": 1},
        ]  # fmt: skip
        return {
            "schema": 2,
            "match_id": "m1",
            "fighters": {"a": fighter(a), "b": fighter(b)},
            "turns": [{"turn": 1, "events": events}],
        }

    return make
