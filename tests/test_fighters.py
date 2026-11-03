import logging
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena_api import fighters, store
from arena_api.app import app
from arena_api.fighter_routes import MAX_FIGHTERS_PER_USER
from arena_api.secret_box import decrypt

type SignIn = Callable[[str], TestClient]

KEY = "gsk_test_abcdefghij1234"
BODY: dict[str, Any] = {
    "name": "rex",
    "provider": "groq",
    "model": "llama-test",
    "persona": "You are a careful competitor.",
    "api_key": KEY,
}


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None) -> None:
    """Every test here needs the provider config and a server secret for keys."""


def create(client: TestClient, **changes: Any) -> Any:
    return client.post("/fighters", json=BODY | changes)


def test_creating_a_fighter_returns_it_without_the_key(sign_in: SignIn) -> None:
    client = sign_in("ada")

    response = create(client)

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["version"], body["provider"], body["model"]) == (
        "rex", 1, "groq", "llama-test",
    )  # fmt: skip
    assert body["persona"] == "You are a careful competitor."
    assert body["key_hint"] == "1234"
    assert body["verified"] is False
    assert KEY not in response.text and "api_key" not in body


def test_the_key_is_stored_encrypted_and_can_be_recovered_by_the_server(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = create(client).json()["id"]

    stored = fighters.current_version(fighter_id)

    assert stored is not None and KEY not in stored.api_key_encrypted
    assert decrypt(stored.api_key_encrypted) == KEY


def test_the_key_never_reaches_the_logs(sign_in: SignIn, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    client = sign_in("ada")
    create(client)
    client.get("/fighters")

    assert KEY not in caplog.text


def test_every_fighter_route_needs_a_session(database: str, config_file: object) -> None:
    anonymous = TestClient(app)

    assert anonymous.get("/fighters").status_code == 401
    assert anonymous.post("/fighters", json=BODY).status_code == 401
    assert anonymous.get("/fighters/1").status_code == 401
    assert anonymous.post("/fighters/1/versions", json=BODY).status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": "has space"},
        {"name": "x" * 33},
        {"provider": "not-a-provider"},
        {"model": ""},
        {"persona": ""},
        {"persona": "x" * 2001},
        {"api_key": "short"},
        {"api_key": "has a space in it 1234"},
        {"daily_match_cap": 0},
        {"daily_match_cap": 51},
    ],
)
def test_bad_input_is_rejected_and_nothing_is_saved(sign_in: SignIn, bad: dict[str, Any]) -> None:
    client = sign_in("ada")

    assert create(client, **bad).status_code == 422
    assert client.get("/fighters").json() == []


def test_a_name_is_unique_per_owner_but_not_across_owners(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    create(ada)

    assert create(ada).status_code == 409
    assert create(bob).status_code == 201


def test_a_user_can_only_have_so_many_fighters(sign_in: SignIn) -> None:
    client = sign_in("ada")
    for i in range(MAX_FIGHTERS_PER_USER):
        assert create(client, name=f"f{i}").status_code == 201

    assert create(client, name="one-too-many").status_code == 409


def test_you_only_see_and_open_your_own_fighters(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    mine = create(ada).json()["id"]

    assert [f["id"] for f in ada.get("/fighters").json()] == [mine]
    assert bob.get("/fighters").json() == []
    assert ada.get(f"/fighters/{mine}").status_code == 200
    assert bob.get(f"/fighters/{mine}").status_code == 404
    assert bob.post(f"/fighters/{mine}/versions", json=BODY).status_code == 404


def test_an_edit_makes_a_new_version_and_keeps_the_key_unless_replaced(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = create(client).json()["id"]
    edit = {k: v for k, v in BODY.items() if k not in ("name", "api_key")}

    second = client.post(f"/fighters/{fighter_id}/versions", json=edit | {"persona": "Be bold."})

    assert second.status_code == 201
    assert (second.json()["version"], second.json()["persona"]) == (2, "Be bold.")
    assert second.json()["key_hint"] == "1234"
    version = fighters.current_version(fighter_id)
    assert version is not None and decrypt(version.api_key_encrypted) == KEY

    third = client.post(
        f"/fighters/{fighter_id}/versions", json=edit | {"api_key": "gsk_replacement_5678"}
    )

    assert (third.json()["version"], third.json()["key_hint"]) == (3, "5678")
    version = fighters.current_version(fighter_id)
    assert version is not None and decrypt(version.api_key_encrypted) == "gsk_replacement_5678"


def test_a_new_version_starts_unverified_but_the_old_one_stays_on_record(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = create(client).json()["id"]
    with store.connect() as conn:
        conn.execute("UPDATE fighter_versions SET verified_at = now() WHERE version = 1")
    assert client.get(f"/fighters/{fighter_id}").json()["verified"] is True
    edit = {k: v for k, v in BODY.items() if k not in ("name", "api_key")}

    client.post(f"/fighters/{fighter_id}/versions", json=edit)

    assert client.get(f"/fighters/{fighter_id}").json()["verified"] is False
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT version, verified_at IS NOT NULL AS verified FROM fighter_versions "
            "ORDER BY version"
        ).fetchall()
    assert [(r["version"], r["verified"]) for r in rows] == [(1, True), (2, False)]


def test_a_cap_can_be_set_and_changed_with_a_version(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = create(client, daily_match_cap=3).json()["id"]
    assert client.get(f"/fighters/{fighter_id}").json()["daily_match_cap"] == 3
    edit = {k: v for k, v in BODY.items() if k not in ("name", "api_key")}

    client.post(f"/fighters/{fighter_id}/versions", json=edit | {"daily_match_cap": 7})

    assert client.get(f"/fighters/{fighter_id}").json()["daily_match_cap"] == 7


def test_options_list_the_providers_and_persona_templates(sign_in: SignIn) -> None:
    options = sign_in("ada").get("/fighters/options").json()

    assert sorted(options["providers"]) == ["gemini", "groq"]
    assert {t["name"] for t in options["templates"]} == {
        "Aggressive",
        "Defensive",
        "Counter-puncher",
    }
    assert all(t["persona"] for t in options["templates"])
