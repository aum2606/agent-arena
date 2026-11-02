import os
from pathlib import Path

import psycopg

from arena.config import ConfigError

MIGRATIONS = Path(__file__).parent / "migrations"
# Arbitrary key: API and worker both migrate on start, and this makes them take turns.
_MIGRATION_LOCK = 8_431_207


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"{name} is not set (see .env.example)")
    return value


def database_url() -> str:
    return _env("DATABASE_URL")


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def fighters_config_path() -> Path:
    return Path(os.environ.get("FIGHTERS_CONFIG", "config/fighters.toml"))


def migrate() -> None:
    """Apply the numbered .sql files in `migrations/` that have not run yet."""
    with psycopg.connect(database_url()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name not in applied:
                # Our own file shipped with the code, never user input.
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
