from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from arena_api import store
from arena_api.app import MAX_QUEUED, app, get_queue

CONFIG = """
[settings]
turn_time_limit_s = 30.0
turn_max_tokens = 256
defender_max_tokens = 128
snippet_timeout_s = 5.0
call_delay_s = 0.0
max_retries = 0
backoff_base_s = 0.0

[providers.p]
base_url = "https://example.test/v1"
api_key_env = "P_API_KEY"

[[fighters]]
name = "alice"
provider = "p"
model = "m"
persona = "persona a"

[[fighters]]
name = "bob"
provider = "p"
model = "m"
persona = "persona b"
"""


class StubQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []
        self.error = error

    async def enqueue_job(self, function: str, *args: Any) -> None:
        if self.error:
            raise self.error
        self.jobs.append((function, args))


@pytest.fixture
def queue() -> Iterator[StubQueue]:
    stub = StubQueue()
    app.dependency_overrides[get_queue] = lambda: stub
    yield stub
    app.dependency_overrides.clear()


@pytest.fixture
def client(database: str, queue: StubQueue, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "fighters.toml"
    path.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("FIGHTERS_CONFIG", str(path))
    return TestClient(app)


def start(client: TestClient, a: str = "alice", b: str = "bob"):
    return client.post("/matches", json={"fighter_a": a, "fighter_b": b})


def test_starting_a_match_saves_it_and_queues_one_job(client: TestClient, queue: StubQueue) -> None:
    response = start(client)

    assert response.status_code == 202
    body = response.json()
    assert (body["status"], body["fighter_a"], body["fighter_b"]) == ("queued", "alice", "bob")
    assert queue.jobs == [("play_match", (body["id"],))]
    assert store.get_match(body["id"]) is not None


@pytest.mark.parametrize(("a", "b"), [("alice", "nobody"), ("nobody", "bob"), ("alice", "alice")])
def test_unknown_or_identical_fighters_are_rejected_and_nothing_is_queued(
    client: TestClient, queue: StubQueue, a: str, b: str
) -> None:
    assert start(client, a, b).status_code == 422
    assert queue.jobs == []
    assert store.count_queued() == 0


def test_a_full_queue_turns_new_matches_away(client: TestClient, queue: StubQueue) -> None:
    for i in range(MAX_QUEUED):
        store.create_match(f"waiting{i}", "alice", "bob")

    assert start(client).status_code == 429
    assert queue.jobs == []


def test_if_the_queue_is_down_the_match_is_failed_not_left_waiting(
    client: TestClient, queue: StubQueue
) -> None:
    queue.error = RedisConnectionError("redis is down")

    response = start(client)

    assert response.status_code == 503
    assert store.count_queued() == 0


def test_a_match_reports_its_status(client: TestClient) -> None:
    match_id = start(client).json()["id"]
    store.mark_failed(match_id, "groq rate limited after 8 retries")

    body = client.get(f"/matches/{match_id}").json()

    assert body == {
        "id": match_id,
        "status": "failed",
        "fighter_a": "alice",
        "fighter_b": "bob",
        "error": "groq rate limited after 8 retries",
    }


def test_unknown_match_is_404(client: TestClient) -> None:
    assert client.get("/matches/nope").status_code == 404
