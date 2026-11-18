"""A record of the events someone investigating an incident would ask about (D-081)."""

import logging

import pytest
from fastapi.testclient import TestClient
from helpers import FIGHTER, SignIn, StubQueue, make_fighter

from arena_api import security_log
from arena_api.app import app
from arena_api.visitor_limits import VISITOR_RULES


@pytest.fixture(autouse=True)
def setup(
    config_file: object, encryption: None, queue: StubQueue, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="arena.security")


def events(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "arena.security"]


def test_a_line_is_key_value_pairs_and_cannot_be_forged_with_a_newline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    newline = chr(10)
    security_log.record("sample", note=f"first{newline}second event=fake", long="x" * 500, empty="")

    (line,) = events(caplog)
    assert newline not in line
    # A value with spaces or odd characters is quoted, so it cannot start a field of its own.
    assert line == f'security event=sample note="first second event=fake" long={"x" * 100} empty=""'


def test_signing_in_is_recorded_without_the_session_token(
    sign_in: SignIn, caplog: pytest.LogCaptureFixture
) -> None:
    client = sign_in("ada")

    lines = events(caplog)
    assert any(
        line.startswith("security event=login ") and "provider=dev" in line for line in lines
    )
    assert client.cookies.get("arena_session") not in " ".join(lines)


def test_a_cross_site_write_and_an_oversized_body_are_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(app)

    client.post("/auth/logout", headers={"origin": "https://evil.example"})
    client.post("/fighters", content=b"x" * 70_000)

    lines = " | ".join(events(caplog))
    assert "event=request_refused" in lines and "status=403" in lines and "status=413" in lines


def test_a_refused_dev_login_through_a_tunnel_is_recorded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")
    client = TestClient(app)

    client.post("/auth/dev", json={"handle": "mallory"}, headers={"x-forwarded-for": "203.0.113.5"})

    assert any("event=dev_login_refused" in line for line in events(caplog))


def test_key_changes_fighter_deletes_and_account_events_are_recorded_without_the_key(
    sign_in: SignIn, caplog: pytest.LogCaptureFixture
) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    edit = {"provider": "groq", "model": "m", "persona": "p", "api_key": "gsk_new_key_123456"}
    client.post(f"/fighters/{fighter_id}/versions", json=edit)
    client.put(f"/fighters/{fighter_id}/ranked-pool", json={"enabled": True})
    client.delete(f"/fighters/{fighter_id}")
    client.post("/auth/logout-all")
    sign_in("bob").delete("/auth/me")

    text = " | ".join(events(caplog))
    expected = [
        "fighter_created",
        "key_changed",
        "ranked_pool",
        "fighter_deleted",
        "logout_all",
        "account_deleted",
    ]
    for name in expected:
        assert f"event={name}" in text, name
    assert FIGHTER["api_key"] not in text and "gsk_new_key_123456" not in text


def test_a_rate_limited_request_is_recorded_by_rule_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "session", (1, 60))
    client = TestClient(app)

    client.get("/auth/me")
    client.get("/auth/me")

    assert any("event=rate_limited" in line and "rule=session" in line for line in events(caplog))
