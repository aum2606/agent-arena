"""What a user can do about their own sessions and data (D-078)."""

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from helpers import SignIn, StubQueue, make_fighter
from test_ranked import BOB_KEY, finished_match, verified

from arena_api import fighters, rotate_keys, store
from arena_api.app import app
from arena_api.secret_box import decrypt


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """These tests need the provider config, a key secret and the stand-in Redis."""


def rows(sql: str, *params: Any) -> list[dict[str, Any]]:
    with store.connect() as conn:
        return list(conn.execute(sql, params).fetchall())


def test_logging_out_everywhere_ends_every_session_of_that_user_only(sign_in: SignIn) -> None:
    phone, laptop, other = sign_in("ada"), sign_in("ada"), sign_in("bob")

    assert phone.post("/auth/logout-all").status_code == 204

    assert phone.get("/auth/me").status_code == 401
    assert laptop.get("/auth/me").status_code == 401  # the other device was signed out too
    assert other.get("/auth/me").status_code == 200


def test_logging_out_everywhere_needs_a_session() -> None:
    assert TestClient(app).post("/auth/logout-all").status_code == 401


def test_expired_sessions_are_deleted_by_the_next_sign_in(sign_in: SignIn) -> None:
    sign_in("ada")
    with store.connect() as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 day'")
    assert rows("SELECT count(*) AS n FROM sessions")[0]["n"] == 1

    sign_in("bob")

    assert rows("SELECT count(*) AS n FROM sessions")[0]["n"] == 1  # only bob's is left


def test_deleting_an_account_erases_the_user_their_fighters_keys_and_sessions(
    sign_in: SignIn,
) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)

    response = ada.delete("/auth/me")

    assert response.status_code == 204
    assert ada.get("/auth/me").status_code == 401
    assert rows("SELECT id FROM users") == []
    assert rows("SELECT fighter_id FROM fighter_versions") == []  # the encrypted keys went too
    assert fighters.current_version(fighter_id) is None
    assert rows("SELECT token_hash FROM sessions") == []


def test_an_account_with_a_match_in_progress_cannot_be_deleted_yet(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    fighter_id = make_fighter(ada)
    ada.post(f"/fighters/{fighter_id}/spar")

    refused = ada.delete("/auth/me")

    assert refused.status_code == 409
    assert ada.get("/auth/me").status_code == 200


def test_deleting_an_account_removes_its_sparring_replays(sign_in: SignIn) -> None:
    ada = sign_in("ada")
    fighter_id = verified(ada)
    spar_id = str(ada.post(f"/fighters/{fighter_id}/spar").json()["id"])
    with store.connect() as conn:
        conn.execute("UPDATE matches SET status = 'failed' WHERE id = %s", (spar_id,))

    assert ada.delete("/auth/me").status_code == 204

    assert rows("SELECT id FROM matches WHERE mode = 'sparring'") == []


def test_a_ranked_match_stays_for_the_opponent_without_the_deleted_players_name_or_persona(
    sign_in: SignIn,
) -> None:
    match_id = finished_match(sign_in)

    assert sign_in("ada").delete("/auth/me").status_code == 204

    bob = sign_in("bob")
    replay = bob.get(f"/replays/{match_id}")
    assert replay.status_code == 200
    body = replay.json()
    assert body["fighter_a"]["name"] == "deleted"
    assert body["fighter_a"]["persona"] == "[removed]"
    assert body["fighter_b"]["name"] == "bob/rex"  # the opponent's own side is untouched
    assert "ada" not in replay.text
    row = rows("SELECT fighter_a, fighter_b FROM matches WHERE id = %s", match_id)[0]
    assert (row["fighter_a"], row["fighter_b"]) == ("deleted", "bob/rex")
    # Bob keeps the rating the match gave him; Ada's rating went with her fighter.
    assert [r["fighter_id"] for r in rows("SELECT fighter_id FROM ratings")] == [2]


def test_deleting_one_account_leaves_everyone_elses_alone(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    make_fighter(ada)
    bob_fighter = make_fighter(bob)

    ada.delete("/auth/me")

    assert bob.get(f"/fighters/{bob_fighter}").status_code == 200
    assert [r["handle"] for r in rows("SELECT handle FROM users")] == ["bob"]


def test_a_deleted_handle_can_be_taken_again(sign_in: SignIn) -> None:
    sign_in("ada").delete("/auth/me")

    assert sign_in("ada").get("/auth/me").json()["handle"] == "ada"


def test_rotating_the_server_secret_keeps_every_stored_key_readable(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_secret = Fernet.generate_key().decode()
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", old_secret)
    ada, bob = sign_in("ada"), sign_in("bob")
    ids = [make_fighter(ada), make_fighter(ada, name="max"), make_fighter(bob, api_key=BOB_KEY)]
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())
    monkeypatch.setenv("KEY_ENCRYPTION_OLD_SECRETS", old_secret)

    assert rotate_keys.rotate_all() == 3

    monkeypatch.delenv("KEY_ENCRYPTION_OLD_SECRETS")  # the old secret is no longer needed
    for fighter_id in ids:
        version = fighters.current_version(fighter_id)
        assert version is not None and decrypt(version.api_key_encrypted)
