from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from arena_api import store
from arena_api.app import app
from arena_api.fighter_routes import MAX_SPARS_PER_USER_PER_DAY
from arena_api.match_routes import MAX_QUEUED, get_queue

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


@pytest.fixture
def queue() -> Iterator[StubQueue]:
    stub = StubQueue()
    app.dependency_overrides[get_queue] = lambda: stub
    yield stub
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """Spar tests need the provider config, a key secret and a stand-in queue."""


def make_fighter(client: TestClient, **changes: Any) -> int:
    response = client.post("/fighters", json=FIGHTER | changes)
    assert response.status_code == 201
    return int(response.json()["id"])


def spar(client: TestClient, fighter_id: int) -> Any:
    return client.post(f"/fighters/{fighter_id}/spar")


def test_sparring_queues_a_match_against_the_house_bot(sign_in: SignIn, queue: StubQueue) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)

    response = spar(ada, fighter_id)

    assert response.status_code == 202
    body = response.json()
    assert (body["status"], body["fighter_a"], body["fighter_b"]) == ("queued", "ada/rex", "house")
    assert body["fighter_version"] == 1
    assert queue.jobs == [("play_match", (body["id"],))]
    row = store.get_match(body["id"])
    assert row is not None
    assert (row.mode, row.fighter_id, row.fighter_version) == ("sparring", fighter_id, 1)


def test_sparring_uses_the_latest_version(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    edit = {k: v for k, v in FIGHTER.items() if k not in ("name", "api_key")}
    ada.post(f"/fighters/{fighter_id}/versions", json=edit | {"persona": "Be bold."})

    assert spar(ada, fighter_id).json()["fighter_version"] == 2


def test_you_cannot_spar_with_someone_elses_fighter_or_without_signing_in(
    sign_in: SignIn, queue: StubQueue
) -> None:
    fighter_id = make_fighter(sign_in("ada"))

    assert spar(sign_in("bob"), fighter_id).status_code == 404
    assert spar(TestClient(app), fighter_id).status_code == 401
    assert queue.jobs == []


def test_without_a_house_bot_there_is_nobody_to_spar(
    sign_in: SignIn, config_file: Path, queue: StubQueue
) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace('house_bot = "house"\n', ""),
        encoding="utf-8",
    )

    assert spar(ada, fighter_id).status_code == 503
    assert queue.jobs == []


def test_a_fighter_stops_at_its_daily_cap(sign_in: SignIn, queue: StubQueue) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada, daily_match_cap=1)

    assert spar(ada, fighter_id).status_code == 202
    assert spar(ada, fighter_id).status_code == 429
    assert len(queue.jobs) == 1


def test_a_user_stops_at_the_daily_spar_limit_across_fighters(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    ids = [make_fighter(ada, name=f"f{i}") for i in range(MAX_SPARS_PER_USER_PER_DAY + 1)]

    results = [spar(ada, fighter_id).status_code for fighter_id in ids]

    assert results == [202] * MAX_SPARS_PER_USER_PER_DAY + [429]


def test_old_matches_no_longer_count_against_the_caps(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada, daily_match_cap=1)
    spar(ada, fighter_id)
    with store.connect() as conn:
        conn.execute("UPDATE matches SET created_at = now() - interval '25 hours'")

    assert spar(ada, fighter_id).status_code == 202


def test_a_full_queue_turns_new_matches_away(sign_in: SignIn, queue: StubQueue) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    for i in range(MAX_QUEUED):
        store.create_match(f"waiting{i}", "x", "y")

    assert spar(ada, fighter_id).status_code == 429
    assert queue.jobs == []


def test_if_the_queue_is_down_the_match_is_failed_not_left_waiting(
    sign_in: SignIn, queue: StubQueue
) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    queue.error = RedisConnectionError("redis is down")

    assert spar(ada, fighter_id).status_code == 503
    assert store.count_queued() == 0


def test_only_the_owner_can_see_a_sparring_match_status(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    match_id = spar(ada, make_fighter(ada)).json()["id"]
    store.mark_failed(match_id, "groq returned HTTP 401")

    mine = ada.get(f"/matches/{match_id}")

    assert mine.status_code == 200 and mine.json()["error"] == "groq returned HTTP 401"
    assert sign_in("bob").get(f"/matches/{match_id}").status_code == 404
    assert TestClient(app).get(f"/matches/{match_id}").status_code == 401
    assert ada.get("/matches/nope").status_code == 404


def test_a_fighters_recent_spars_are_listed_newest_first_to_its_owner_only(
    sign_in: SignIn,
) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    first = spar(ada, fighter_id).json()["id"]
    second = spar(ada, fighter_id).json()["id"]

    listed = ada.get(f"/fighters/{fighter_id}/spars").json()

    assert [m["id"] for m in listed] == [second, first]
    assert sign_in("bob").get(f"/fighters/{fighter_id}/spars").status_code == 404


def finished_spar(ada: TestClient, sample_log: Callable[..., dict[str, Any]]) -> str:
    match_id = spar(ada, make_fighter(ada)).json()["id"]
    log = sample_log("ada/rex", "house")
    from arena_api.replays import parse_replay

    store.mark_running(match_id)
    store.mark_finished(match_id, log, parse_replay(match_id, log).summary)
    return match_id


def test_a_sparring_replay_is_private_to_its_owner(
    sign_in: SignIn, sample_log: Callable[..., dict[str, Any]]
) -> None:
    ada = sign_in("ada")
    match_id = finished_spar(ada, sample_log)

    assert ada.get(f"/replays/{match_id}").status_code == 200
    assert sign_in("bob").get(f"/replays/{match_id}").status_code == 404
    assert TestClient(app).get(f"/replays/{match_id}").status_code == 404


def test_sparring_matches_are_not_in_the_public_replay_list(
    sign_in: SignIn, sample_log: Callable[..., dict[str, Any]]
) -> None:
    finished_spar(sign_in("ada"), sample_log)

    assert TestClient(app).get("/replays").json() == []
