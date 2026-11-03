from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient

from arena_api import accounts, store
from arena_api.app import app
from arena_api.auth import get_github_http

type Handler = Callable[[httpx2.Request], httpx2.Response]


def github(login: str = "octo", user_id: int = 4242, token: str | None = "gh-token") -> Handler:
    """A stand-in for github.com: exchanges any code for a token, then knows one user."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx2.Response(
                200, json={"access_token": token} if token else {"error": "bad_code"}
            )
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer gh-token"
            return httpx2.Response(200, json={"id": user_id, "login": login})
        return httpx2.Response(404)

    return handle


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://127.0.0.1:3100")


@pytest.fixture
def use_github() -> Iterator[Callable[[Handler], None]]:
    def install(handler: Handler) -> None:
        client = httpx2.Client(transport=httpx2.MockTransport(handler))
        app.dependency_overrides[get_github_http] = lambda: client

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def client(database: str, env: None) -> TestClient:
    return TestClient(app, follow_redirects=False)


def sign_in(client: TestClient, use_github: Callable[[Handler], None], **kwargs: Any) -> None:
    use_github(github(**kwargs))
    started = client.get("/auth/github/login")
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    client.get("/auth/github/callback", params={"code": "abc", "state": state})


def test_login_sends_the_browser_to_github_with_a_state_it_remembers(client: TestClient) -> None:
    response = client.get("/auth/github/login")

    assert response.status_code == 307
    target = urlparse(response.headers["location"])
    query = parse_qs(target.query)
    assert (target.netloc, target.path) == ("github.com", "/login/oauth/authorize")
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://127.0.0.1:3100/api/auth/github/callback"]
    assert response.cookies["arena_oauth_state"] == query["state"][0]


def test_a_good_callback_creates_the_user_and_a_session(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    sign_in(client, use_github)

    me = client.get("/auth/me")

    assert me.status_code == 200
    assert me.json() == {"id": me.json()["id"], "handle": "octo"}
    token = client.cookies["arena_session"]
    # Only a hash of the token is stored, so a database leak does not hand out sessions.
    assert accounts.user_for_token(token) is not None
    with store.connect() as conn:
        stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert stored and token not in stored


def test_the_session_cookie_cannot_be_read_by_scripts(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    use_github(github())
    state = parse_qs(urlparse(client.get("/auth/github/login").headers["location"]).query)["state"][
        0
    ]

    response = client.get("/auth/github/callback", params={"code": "abc", "state": state})

    assert response.status_code == 307 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_signing_in_again_keeps_the_same_user(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    sign_in(client, use_github, login="octo")
    first = client.get("/auth/me").json()["id"]
    client.cookies.clear()

    sign_in(client, use_github, login="octo-renamed")

    me = client.get("/auth/me").json()
    assert (me["id"], me["handle"]) == (first, "octo-renamed")


@pytest.mark.parametrize("state", ["wrong", ""])
def test_a_callback_with_the_wrong_state_is_refused(
    client: TestClient, use_github: Callable[[Handler], None], state: str
) -> None:
    use_github(github())
    client.get("/auth/github/login")

    response = client.get("/auth/github/callback", params={"code": "abc", "state": state})

    assert response.status_code == 400
    assert client.get("/auth/me").status_code == 401


def test_a_callback_without_a_state_cookie_is_refused(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    use_github(github())

    response = client.get("/auth/github/callback", params={"code": "abc", "state": "anything"})

    assert response.status_code == 400


def test_github_refusing_the_code_signs_nobody_in(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    sign_in(client, use_github, token=None)

    assert client.get("/auth/me").status_code == 401


def test_without_github_settings_sign_in_says_so(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)

    response = TestClient(app, follow_redirects=False).get("/auth/github/login")

    assert response.status_code == 503
    assert "GITHUB_CLIENT_ID" in response.json()["detail"]


def test_no_cookie_or_an_unknown_one_is_signed_out(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401
    client.cookies.set("arena_session", "not-a-real-token")
    assert client.get("/auth/me").status_code == 401


def test_an_expired_session_is_signed_out(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    sign_in(client, use_github)
    with store.connect() as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")

    assert client.get("/auth/me").status_code == 401


def test_logging_out_ends_the_session(
    client: TestClient, use_github: Callable[[Handler], None]
) -> None:
    sign_in(client, use_github)

    assert client.post("/auth/logout").status_code == 204

    assert client.get("/auth/me").status_code == 401
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM sessions").fetchone() == {"n": 0}


def test_dev_login_is_off_unless_asked_for(client: TestClient) -> None:
    assert client.post("/auth/dev", json={"handle": "tester"}).status_code == 404
    assert client.get("/auth/config").json() == {"github": True, "dev_login": False}


def test_dev_login_signs_in_a_named_user_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")

    assert client.post("/auth/dev", json={"handle": "tester"}).status_code == 204

    assert client.get("/auth/me").json()["handle"] == "tester"
    assert client.get("/auth/config").json()["dev_login"] is True


@pytest.mark.parametrize("handle", ["", "has space", "x" * 40, "../etc"])
def test_dev_login_rejects_odd_handles(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, handle: str
) -> None:
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")

    assert client.post("/auth/dev", json={"handle": handle}).status_code == 422
