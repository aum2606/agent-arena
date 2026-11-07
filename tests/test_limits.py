import pytest
from fastapi.testclient import TestClient
from helpers import SignIn, StubQueue, make_fighter
from redis.exceptions import ConnectionError as RedisConnectionError

from arena_api.limits import RULES


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """Needs the provider config, a key secret and the stand-in Redis."""


def test_the_write_routes_have_a_limit_each() -> None:
    assert set(RULES) == {"create_fighter", "new_version", "spar", "ranked"}


def test_a_user_past_the_limit_is_turned_away_with_a_wait_time(
    sign_in: SignIn, queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(RULES, "create_fighter", (2, 60))
    ada = sign_in("ada")

    codes = [ada.post("/fighters", json=body(f"f{i}")).status_code for i in range(4)]

    assert codes == [201, 201, 429, 429]
    refused = ada.post("/fighters", json=body("again"))
    assert refused.json()["detail"].startswith("too many requests")
    assert refused.headers["retry-after"] == "60"
    assert list(queue.expiries.values()) == [60]  # a counter always expires on its own


def test_limits_are_per_user_and_per_route(
    sign_in: SignIn, queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(RULES, "create_fighter", (1, 60))
    ada, bob = sign_in("ada"), sign_in("bob")

    assert ada.post("/fighters", json=body("a")).status_code == 201
    assert ada.post("/fighters", json=body("b")).status_code == 429
    assert bob.post("/fighters", json=body("a")).status_code == 201  # another user
    assert ada.get("/fighters").status_code == 200  # reading is never limited


def test_a_redis_outage_does_not_block_the_route(sign_in: SignIn, queue: StubQueue) -> None:
    ada = sign_in("ada")
    queue.counter_error = RedisConnectionError("redis is down")

    assert ada.post("/fighters", json=body("a")).status_code == 201


def test_spar_and_ranked_are_limited_too(sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RULES, "spar", (1, 60))
    monkeypatch.setitem(RULES, "ranked", (1, 60))
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)

    assert ada.post(f"/fighters/{fighter_id}/spar").status_code == 202
    assert ada.post(f"/fighters/{fighter_id}/spar").status_code == 429
    assert (
        ada.post(f"/fighters/{fighter_id}/ranked").status_code == 409
    )  # not verified: past the limiter
    assert ada.post(f"/fighters/{fighter_id}/ranked").status_code == 429


def test_a_new_version_is_limited(sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RULES, "new_version", (1, 86400))
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    edit = {k: v for k, v in body("x").items() if k not in ("name", "api_key")}

    assert ada.post(f"/fighters/{fighter_id}/versions", json=edit).status_code == 201
    assert ada.post(f"/fighters/{fighter_id}/versions", json=edit).status_code == 429


def body(name: str) -> dict[str, str]:
    return {
        "name": name,
        "provider": "groq",
        "model": "llama-test",
        "persona": "You are a careful competitor.",
        "api_key": "gsk_test_abcdefghij1234",
    }


def test_the_signed_out_get_401_not_429(queue: StubQueue) -> None:
    from arena_api.app import app

    assert TestClient(app).post("/fighters", json=body("a")).status_code == 401
