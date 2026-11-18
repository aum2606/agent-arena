"""Limits on what one person, or a few friends, can spend or distort (D-077)."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import SignIn, StubQueue, make_fighter
from test_ranked import BOB_KEY, a_wins, play, ranked, verified

from arena_api import ranked_routes, store
from arena_api.app import app
from arena_api.visitor_limits import VISITOR_RULES


@pytest.fixture(autouse=True)
def setup(config_file: object, encryption: None, queue: StubQueue) -> None:
    """These tests need the provider config, a key secret and the stand-in Redis."""


def set_budget(matches: int) -> None:
    path = Path(os.environ["FIGHTERS_CONFIG"])
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "backoff_base_s = 0.0", f"backoff_base_s = 0.0\nserver_matches_per_day = {matches}"
        ),
        encoding="utf-8",
    )


def test_the_site_wide_budget_of_server_paid_matches_runs_out(
    sign_in: SignIn, queue: StubQueue
) -> None:
    set_budget(2)
    fighters = [make_fighter(sign_in(handle)) for handle in ("ada", "bob", "cy")]
    clients = [sign_in(handle) for handle in ("ada", "bob", "cy")]

    codes = [
        c.post(f"/fighters/{f}/spar").status_code for c, f in zip(clients, fighters, strict=True)
    ]

    assert codes == [202, 202, 429]
    refused = clients[2].post(f"/fighters/{fighters[2]}/spar")
    assert "budget" in refused.json()["detail"]
    assert queue.expiries["budget:server-matches"] == 86_400  # it resets on its own


def test_a_refused_match_is_not_left_behind_in_the_queue(sign_in: SignIn, queue: StubQueue) -> None:
    set_budget(1)
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_fighter, bob_fighter = make_fighter(ada), make_fighter(bob)
    ada.post(f"/fighters/{ada_fighter}/spar")

    bob.post(f"/fighters/{bob_fighter}/spar")

    assert len(queue.jobs) == 1
    assert bob.get(f"/fighters/{bob_fighter}/spars").json() == []


def test_the_budget_also_covers_ranked_matches(sign_in: SignIn) -> None:
    set_budget(1)
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada)
    bob_id = verified(bob, api_key=BOB_KEY)

    assert ranked(ada, ada_id).status_code == 202
    refused = ranked(bob, bob_id)  # one match was all the budget allowed
    assert refused.status_code == 429 and "budget" in refused.json()["detail"]


def test_a_user_has_a_daily_ranked_limit_across_all_their_fighters(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ranked_routes, "MAX_RANKED_PER_USER_PER_DAY", 1)
    ada, bob = sign_in("ada"), sign_in("bob")
    first = verified(ada)
    second = verified(ada, name="max")
    verified(bob, api_key=BOB_KEY)
    play(str(ranked(ada, first).json()["id"]), a_wins)

    refused = ranked(ada, second)

    assert refused.status_code == 429
    assert "ranked" in refused.json()["detail"]


def test_two_owners_cannot_trade_wins_more_than_three_times_a_day(sign_in: SignIn) -> None:
    ada, bob = sign_in("ada"), sign_in("bob")
    ada_id = verified(ada)
    verified(bob, api_key=BOB_KEY)
    for _ in range(store.MAX_PAIR_MATCHES_PER_DAY):
        started = ranked(ada, ada_id)
        assert started.status_code == 202
        play(str(started.json()["id"]), a_wins)

    refused = ranked(ada, ada_id)

    assert refused.status_code == 409
    assert "no other fighter" in refused.json()["detail"]


def test_a_third_owner_can_still_be_paired_when_the_pair_limit_is_reached(sign_in: SignIn) -> None:
    ada, bob, cy = sign_in("ada"), sign_in("bob"), sign_in("cy")
    ada_id = verified(ada)
    verified(bob, api_key=BOB_KEY)
    for _ in range(store.MAX_PAIR_MATCHES_PER_DAY):
        play(str(ranked(ada, ada_id).json()["id"]), a_wins)
    verified(cy, api_key="gsk_test_cy_key_00000")

    assert ranked(ada, ada_id).status_code == 202


def test_session_checks_are_limited_per_address_even_for_junk_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(VISITOR_RULES, "session", (3, 60))
    client = TestClient(app)

    codes = [client.get("/auth/me").status_code for _ in range(5)]

    assert codes == [401, 401, 401, 429, 429]
    assert client.get("/fighters").status_code == 429  # the signed-in routes share the allowance
    assert client.get("/matches/mine").status_code == 429
