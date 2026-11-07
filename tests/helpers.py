from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

type SignIn = Callable[[str], TestClient]

FIGHTER: dict[str, Any] = {
    "name": "rex",
    "provider": "groq",
    "model": "llama-test",
    "persona": "You are a careful competitor.",
    "api_key": "gsk_test_abcdefghij1234",
}


class StubQueue:
    """Stands in for the arq Redis client: records jobs and keeps rate-limit counters."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []
        self.error: Exception | None = None  # raised when a job is enqueued
        self.counter_error: Exception | None = None  # raised by the counter commands
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def set(self, key: str, value: int, ex: int, nx: bool) -> None:
        if self.counter_error:
            raise self.counter_error
        if not (nx and key in self.counters):
            self.counters[key] = value
            self.expiries[key] = ex

    async def incr(self, key: str) -> int:
        self.counters[key] += 1
        return self.counters[key]

    async def ttl(self, key: str) -> int:
        return self.expiries[key]

    async def enqueue_job(self, function: str, *args: Any) -> None:
        if self.error:
            raise self.error
        self.jobs.append((function, args))


def make_fighter(client: TestClient, **changes: Any) -> int:
    response = client.post("/fighters", json=FIGHTER | changes)
    assert response.status_code == 201
    return int(response.json()["id"])
