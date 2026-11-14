import pytest
from fastapi.testclient import TestClient
from helpers import StubQueue

from arena_api.app import app
from arena_api.deps import get_queue
from arena_api.visitor_limits import VISITOR_RULES


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_api_publishes_no_interactive_docs(path: str) -> None:
    # FastAPI's docs pages load scripts from a CDN on the app's own origin (D-068).
    assert TestClient(app).get(path).status_code == 404


def test_dev_login_is_rate_limited_like_the_other_sign_in_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubQueue()
    app.dependency_overrides[get_queue] = lambda: stub
    monkeypatch.setitem(VISITOR_RULES, "login", (1, 60))
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")
    monkeypatch.setenv("PUBLIC_URL", "http://127.0.0.1:3100")
    try:
        client = TestClient(app)
        bad = {"handle": "not a valid handle!"}  # refused before any database use
        assert client.post("/auth/dev", json=bad).status_code == 422
        assert client.post("/auth/dev", json=bad).status_code == 429
    finally:
        app.dependency_overrides.clear()
