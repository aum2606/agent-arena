"""The API and the worker connect as a role that can only read and write rows (D-079)."""

from pathlib import Path

import pytest
import yaml

from arena_api import db

ROOT = Path(__file__).parents[1]
INIT = ROOT / "docker" / "postgres-init" / "10-app-role.sh"
PROD = ROOT / "docker-compose.prod.yml"


def services() -> dict[str, dict[str, object]]:
    return yaml.safe_load(PROD.read_text(encoding="utf-8"))["services"]  # type: ignore[no-any-return]


def env_of(service: str) -> dict[str, str]:
    env = services()[service]["environment"]
    assert isinstance(env, dict)
    return env


def test_migrations_run_on_start_unless_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[bool] = []
    monkeypatch.setattr(db, "migrate", lambda: ran.append(True))

    monkeypatch.delenv("ARENA_AUTO_MIGRATE", raising=False)
    db.migrate_on_start()
    assert ran == [True]  # the default: local development and the tests

    monkeypatch.setenv("ARENA_AUTO_MIGRATE", "0")
    db.migrate_on_start()
    assert ran == [True]  # a deployment with a separate migration step


def test_the_init_script_makes_a_role_that_cannot_do_anything_but_read_and_write_rows() -> None:
    script = INIT.read_text(encoding="utf-8")

    for refused in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE"):
        assert refused in script
    assert "SELECT, INSERT, UPDATE, DELETE" in script
    assert "PASSWORD :'app_password'" in script  # from the environment, never written into the file
    assert "ALL PRIVILEGES" not in script


def test_the_database_starts_with_the_init_script_and_both_passwords() -> None:
    postgres = services()["postgres"]

    assert any("postgres-init" in str(v) for v in postgres["volumes"])  # type: ignore[attr-defined]
    assert ":?" in env_of("postgres")["APP_DB_PASSWORD"]


def test_the_api_connects_as_the_limited_role_and_does_not_migrate() -> None:
    api = env_of("api")

    assert "arena_app" in api["DATABASE_URL"] and "APP_DB_PASSWORD" in api["DATABASE_URL"]
    assert (
        "POSTGRES_PASSWORD" not in api["DATABASE_URL"]
    )  # the owner's password is not in its environment
    assert api["ARENA_AUTO_MIGRATE"] == "0"


def test_only_a_one_shot_migration_service_holds_the_owners_password() -> None:
    migrate = services()["migrate"]
    env = env_of("migrate")

    assert "POSTGRES_PASSWORD" in env["DATABASE_URL"] and "arena_app" not in env["DATABASE_URL"]
    assert migrate["restart"] == "no"
    assert "arena_api.migrate" in " ".join(migrate["command"])  # type: ignore[attr-defined]
    api_waits = services()["api"]["depends_on"]
    assert api_waits["migrate"]["condition"] == "service_completed_successfully"  # type: ignore[index]
