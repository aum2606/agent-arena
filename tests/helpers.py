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
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []
        self.error: Exception | None = None

    async def enqueue_job(self, function: str, *args: Any) -> None:
        if self.error:
            raise self.error
        self.jobs.append((function, args))


def make_fighter(client: TestClient, **changes: Any) -> int:
    response = client.post("/fighters", json=FIGHTER | changes)
    assert response.status_code == 201
    return int(response.json()["id"])
