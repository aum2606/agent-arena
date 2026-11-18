import asyncio
from typing import Any

import pytest

from arena.config import ConfigError
from arena_api import app as app_module
from arena_api import jobs


@pytest.fixture(autouse=True)
def no_secret(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Nothing may touch the database or Redis: the secret is checked first. Returns what ran."""
    monkeypatch.delenv("KEY_ENCRYPTION_SECRET", raising=False)
    ran: list[str] = []
    monkeypatch.setattr(app_module, "migrate_on_start", lambda: ran.append("api migrate"))
    monkeypatch.setattr(jobs, "migrate_on_start", lambda: ran.append("worker migrate"))
    return ran


def test_the_api_will_not_start_without_the_key_secret(no_secret: list[str]) -> None:
    async def start() -> None:
        async with app_module.lifespan(app_module.app):
            pass

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_SECRET"):
        asyncio.run(start())

    assert no_secret == []


def test_the_worker_will_not_start_without_the_key_secret(no_secret: list[str]) -> None:
    ctx: dict[str, Any] = {}

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_SECRET"):
        asyncio.run(jobs.startup(ctx))

    assert no_secret == [] and ctx == {}
