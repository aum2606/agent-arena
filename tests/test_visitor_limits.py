import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from helpers import StubQueue
from redis.exceptions import ConnectionError as RedisConnectionError

from arena_api.deps import get_queue
from arena_api.visitor_limits import VISITOR_RULES, visitor_limit

ADDRESS_HEADER = "x-real-ip"


def page(queue: StubQueue, name: str = "read") -> TestClient:
    """A one-route app guarded by the visitor limit, with the stand-in Redis."""
    app = FastAPI()
    app.dependency_overrides[get_queue] = lambda: queue

    @app.get("/page", dependencies=[Depends(visitor_limit(name))])
    def show() -> dict[str, str]:
        return {"page": "ok"}

    return TestClient(app)


@pytest.fixture
def queue() -> StubQueue:
    return StubQueue()


def test_the_public_routes_have_a_limit_each() -> None:
    assert set(VISITOR_RULES) == {"read", "login"}


def test_a_visitor_past_the_limit_is_turned_away_with_a_wait_time(
    queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "read", (2, 60))
    client = page(queue)

    codes = [client.get("/page").status_code for _ in range(4)]

    assert codes == [200, 200, 429, 429]
    refused = client.get("/page")
    assert refused.json()["detail"].startswith("too many requests")
    assert refused.headers["retry-after"] == "60"
    assert list(queue.expiries.values()) == [60]  # a counter always expires on its own


def test_visitors_are_told_apart_by_the_address_header_the_proxy_sets(
    queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "read", (1, 60))
    monkeypatch.setenv("CLIENT_IP_HEADER", ADDRESS_HEADER)
    client = page(queue)

    def visit(address: str) -> int:
        return client.get("/page", headers={ADDRESS_HEADER: address}).status_code

    assert visit("203.0.113.5") == 200
    assert visit("203.0.113.5") == 429
    assert visit("203.0.113.6") == 200  # another visitor
    assert visit("2001:db8::1") == 200  # IPv6 works too


def test_without_the_setting_the_header_is_not_trusted(
    queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "read", (1, 60))
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    client = page(queue)

    assert client.get("/page", headers={ADDRESS_HEADER: "203.0.113.5"}).status_code == 200
    # A made-up header must not buy a fresh allowance.
    assert client.get("/page", headers={ADDRESS_HEADER: "203.0.113.6"}).status_code == 429


@pytest.mark.parametrize("value", ["", "not an address", "203.0.113.5, 10.0.0.1", "999.1.1.1"])
def test_a_header_that_is_not_one_address_falls_back_to_the_connection(
    queue: StubQueue, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "read", (1, 60))
    monkeypatch.setenv("CLIENT_IP_HEADER", ADDRESS_HEADER)
    client = page(queue)

    assert client.get("/page", headers={ADDRESS_HEADER: value}).status_code == 200
    assert client.get("/page", headers={ADDRESS_HEADER: value + "x"}).status_code == 429


def test_each_rule_counts_on_its_own(queue: StubQueue, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(VISITOR_RULES, "read", (1, 60))
    monkeypatch.setitem(VISITOR_RULES, "login", (1, 60))
    reading, signing_in = page(queue, "read"), page(queue, "login")

    assert reading.get("/page").status_code == 200
    assert reading.get("/page").status_code == 429
    assert signing_in.get("/page").status_code == 200


def test_a_redis_outage_does_not_block_visitors(queue: StubQueue) -> None:
    queue.counter_error = RedisConnectionError("redis is down")

    assert page(queue).get("/page").status_code == 200


def test_the_real_sign_in_routes_are_limited(
    queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arena_api.app import app

    monkeypatch.setitem(VISITOR_RULES, "login", (1, 60))
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
    app.dependency_overrides[get_queue] = lambda: queue
    try:
        client = TestClient(app, follow_redirects=False)
        assert client.get("/auth/github/login").status_code == 307
        assert client.get("/auth/github/login").status_code == 429
        assert (
            client.get("/auth/github/callback", params={"code": "c", "state": "s"}).status_code
            == 429
        )
        assert (
            client.get("/auth/me").status_code == 401
        )  # the per-page session check is not limited
    finally:
        app.dependency_overrides.clear()


def test_the_real_read_routes_are_limited(
    database: str, queue: StubQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arena_api.app import app

    monkeypatch.setitem(VISITOR_RULES, "read", (2, 60))
    app.dependency_overrides[get_queue] = lambda: queue
    try:
        client = TestClient(app)
        codes = [client.get(path).status_code for path in ("/replays", "/leaderboard", "/replays")]
        assert codes == [200, 200, 429]
        assert client.get("/replays/m_missing").status_code == 429  # same bucket as the list
        assert client.get("/health").status_code == 200  # the health check is never limited
    finally:
        app.dependency_overrides.clear()
