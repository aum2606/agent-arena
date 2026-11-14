"""Owner control over a fighter and its key: provider changes, deletion, the ranked pool (D-070)."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import FIGHTER, StubQueue, make_fighter

from arena_api import fighters, store
from arena_api.app import app
from arena_api.limits import RULES

type SignIn = Callable[[str], TestClient]


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """Needs the provider config, a key secret and the stand-in Redis."""


EDIT = {k: v for k, v in FIGHTER.items() if k not in ("name", "api_key")}


def test_moving_a_fighter_to_another_provider_needs_a_new_key(sign_in: SignIn) -> None:
    # Without this the saved Groq key would be sent to the other provider as its credential.
    client = sign_in("ada")
    fighter_id = make_fighter(client)

    refused = client.post(f"/fighters/{fighter_id}/versions", json=EDIT | {"provider": "gemini"})

    assert refused.status_code == 422 and "key" in refused.json()["detail"]
    assert fighters.current_version(fighter_id).version == 1  # type: ignore[union-attr]

    moved = client.post(
        f"/fighters/{fighter_id}/versions",
        json=EDIT | {"provider": "gemini", "api_key": "gem_new_key_12345678"},
    )

    assert moved.status_code == 201 and moved.json()["provider"] == "gemini"


def test_a_fighter_starts_out_of_the_ranked_pool_and_its_owner_can_join_and_leave(
    sign_in: SignIn,
) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    assert client.get(f"/fighters/{fighter_id}").json()["ranked_opt_in"] is False

    joined = client.put(f"/fighters/{fighter_id}/ranked-pool", json={"enabled": True})
    assert joined.status_code == 200 and joined.json()["ranked_opt_in"] is True
    assert client.get(f"/fighters/{fighter_id}").json()["ranked_opt_in"] is True

    left = client.put(f"/fighters/{fighter_id}/ranked-pool", json={"enabled": False})
    assert left.json()["ranked_opt_in"] is False


def test_a_new_version_keeps_the_pool_setting(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    client.put(f"/fighters/{fighter_id}/ranked-pool", json={"enabled": True})

    edited = client.post(f"/fighters/{fighter_id}/versions", json=EDIT | {"persona": "Be bold."})

    assert edited.json()["ranked_opt_in"] is True


def test_only_the_owner_can_change_the_pool_setting(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    fighter_id = make_fighter(ada)

    assert bob.put(f"/fighters/{fighter_id}/ranked-pool", json={"enabled": True}).status_code == 404


def test_a_fighter_must_be_in_the_pool_to_ask_for_a_ranked_match(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    fighters.mark_verified(fighter_id, 1)

    refused = client.post(f"/fighters/{fighter_id}/ranked")

    assert refused.status_code == 409 and "ranked" in refused.json()["detail"]


def test_only_fighters_in_the_pool_are_picked_as_opponents(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id, bob_id = make_fighter(ada), make_fighter(bob)
    for fighter_id in (ada_id, bob_id):
        fighters.mark_verified(fighter_id, 1)
    ada.put(f"/fighters/{ada_id}/ranked-pool", json={"enabled": True})

    assert ada.post(f"/fighters/{ada_id}/ranked").status_code == 409  # bob has not joined

    bob.put(f"/fighters/{bob_id}/ranked-pool", json={"enabled": True})

    assert ada.post(f"/fighters/{ada_id}/ranked").status_code == 202


def test_deleting_a_fighter_erases_it_its_versions_keys_and_rating(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    client.post(f"/fighters/{fighter_id}/versions", json=EDIT | {"persona": "Be bold."})
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO ratings (fighter_id, rating, games) VALUES (%s, 1200, 1)", (fighter_id,)
        )

    deleted = client.delete(f"/fighters/{fighter_id}")

    assert deleted.status_code == 204
    assert client.get(f"/fighters/{fighter_id}").status_code == 404
    assert client.get("/fighters").json() == []
    assert fighters.version(fighter_id, 1) is None and fighters.version(fighter_id, 2) is None
    with store.connect() as conn:
        left = conn.execute(
            "SELECT count(*) AS n FROM ratings WHERE fighter_id = %s", (fighter_id,)
        )
        assert left.fetchone() == {"n": 0}


def test_a_deleted_fighters_finished_matches_stay_on_record(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    store.create_match("s1", "ada/rex", "house", "sparring", 1, fighter_id, 1)
    store.mark_failed("s1", "done")

    assert client.delete(f"/fighters/{fighter_id}").status_code == 204

    row = store.get_match("s1")
    assert row is not None and row.fighter_id is None and row.fighter_a == "ada/rex"


def test_a_fighter_with_a_match_waiting_or_running_cannot_be_deleted(sign_in: SignIn) -> None:
    client = sign_in("ada")
    fighter_id = make_fighter(client)
    assert client.post(f"/fighters/{fighter_id}/spar").status_code == 202

    refused = client.delete(f"/fighters/{fighter_id}")

    assert refused.status_code == 409 and "match" in refused.json()["detail"]
    assert client.get(f"/fighters/{fighter_id}").status_code == 200


def test_nobody_can_delete_someone_elses_fighter(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    fighter_id = make_fighter(ada)

    assert bob.delete(f"/fighters/{fighter_id}").status_code == 404
    assert ada.get(f"/fighters/{fighter_id}").status_code == 200


def test_the_new_routes_need_a_session_and_are_rate_limited(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    anonymous = TestClient(app)
    assert anonymous.delete("/fighters/1").status_code == 401
    assert anonymous.put("/fighters/1/ranked-pool", json={"enabled": True}).status_code == 401
    assert "fighter_edit" in RULES


def test_the_limit_on_edits_covers_deleting(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(RULES, "fighter_edit", (1, 60))
    client = sign_in("ada")
    ids = [make_fighter(client, name=f"f{i}") for i in range(3)]

    codes: list[Any] = [client.delete(f"/fighters/{i}").status_code for i in ids]

    assert codes == [204, 429, 429]
