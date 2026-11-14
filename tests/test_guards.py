"""Guards on every request: cross-site writes, oversized bodies, hidden characters (D-070)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arena_api.app import app
from arena_api.fighter_routes import NewFighter, NewVersion
from arena_api.guards import MAX_BODY_BYTES

PUBLIC = "https://arena.example.com"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PUBLIC_URL", PUBLIC)
    return TestClient(app)


def logout(client: TestClient, **headers: str) -> int:
    return client.post("/auth/logout", headers=headers).status_code  # needs no session


def test_a_write_from_another_origin_is_refused(client: TestClient) -> None:
    assert logout(client, origin="https://evil.example") == 403
    assert logout(client, origin="http://arena.example.com") == 403  # not the same scheme


def test_a_write_from_the_apps_own_origin_goes_through(client: TestClient) -> None:
    assert logout(client, origin=PUBLIC) == 204


def test_a_write_with_no_origin_header_is_not_a_browser_and_goes_through(
    client: TestClient,
) -> None:
    assert logout(client) == 204


@pytest.mark.parametrize(
    ("site", "code"), [("cross-site", 403), ("same-site", 403), ("same-origin", 204), ("none", 204)]
)
def test_the_browsers_own_fetch_metadata_is_honoured(
    client: TestClient, site: str, code: int
) -> None:
    assert logout(client, **{"sec-fetch-site": site}) == code


def test_reading_is_never_blocked_by_an_origin(client: TestClient) -> None:
    assert client.get("/health", headers={"origin": "https://evil.example"}).status_code == 200


def test_on_a_local_address_any_local_port_may_write_but_nobody_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_URL", "http://127.0.0.1:3100")
    local = TestClient(app)

    assert logout(local, origin="http://localhost:3000") == 204  # `npm run dev`
    assert logout(local, origin="http://127.0.0.1:3100") == 204
    assert logout(local, origin="https://evil.example") == 403


def test_a_public_address_does_not_accept_a_local_origin(client: TestClient) -> None:
    assert logout(client, origin="http://localhost:3000") == 403


def test_a_body_over_the_limit_is_refused_before_it_is_read(client: TestClient) -> None:
    big = client.post("/fighters", content=b"x" * (MAX_BODY_BYTES + 1))
    small = client.post("/fighters", content=b"{}")

    assert big.status_code == 413
    assert small.status_code == 401  # reached the route: signed out


def test_a_body_sent_without_a_length_is_refused(client: TestClient) -> None:
    chunked = client.post("/fighters", content=iter([b"{}"]))  # chunked: no Content-Length

    assert chunked.status_code == 411


BASE = {"name": "rex", "provider": "groq", "model": "m", "persona": "p", "api_key": "k" * 20}


@pytest.mark.parametrize("hidden", [chr(0x202E), chr(0x200B), chr(0xE0041), chr(0x07)])
def test_a_persona_or_model_with_invisible_characters_is_rejected(hidden: str) -> None:
    # Both are shown to the other player in a ranked replay, where they could hide text.
    with pytest.raises(ValidationError, match="invisible"):
        NewFighter(**(BASE | {"persona": f"be bold{hidden}"}))
    with pytest.raises(ValidationError, match="invisible"):
        NewFighter(**(BASE | {"model": f"m{hidden}"}))
    with pytest.raises(ValidationError, match="invisible"):
        NewVersion(provider="groq", model="m", persona=f"x{hidden}")


def test_a_persona_may_still_have_newlines_and_tabs() -> None:
    NewFighter(**(BASE | {"persona": "line one\n\tline two\r\nline three"}))


@pytest.mark.parametrize("path", ["/health"])
def test_api_responses_carry_the_small_security_header_set(client: TestClient, path: str) -> None:
    headers = client.get(path).headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["referrer-policy"] == "no-referrer"


def test_refusals_from_the_guard_carry_them_too(client: TestClient) -> None:
    refused = client.post("/fighters", headers={"origin": "https://evil.example"})

    assert refused.status_code == 403 and refused.headers["x-content-type-options"] == "nosniff"
