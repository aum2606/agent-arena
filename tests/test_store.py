from collections.abc import Callable
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from helpers import StubQueue
from psycopg_pool import PoolTimeout

from arena_api import store
from arena_api.app import app
from arena_api.auth import SESSION_COOKIE
from arena_api.db import MIGRATIONS, database_url, migrate
from arena_api.replays import parse_replay

type SampleLog = Callable[..., dict[str, Any]]


def finish(match_id: str, log: dict[str, Any]) -> None:
    store.mark_finished(match_id, log, parse_replay(match_id, log).summary)


def test_new_match_is_queued_with_its_fighters(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    row = store.get_match("m1")

    assert row == store.MatchRow("m1", "queued", "alice", "bob", None)
    assert store.get_match("nope") is None


def test_a_match_can_only_start_running_once(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    assert store.mark_running("m1") is True
    assert store.mark_running("m1") is False
    row = store.get_match("m1")
    assert row is not None and row.status == "running"


def test_finished_matches_are_listed_and_their_log_comes_back(
    database: str, sample_log: SampleLog
) -> None:
    store.create_match("m1", "alice", "bob")
    store.mark_running("m1")
    log = sample_log()

    finish("m1", log)

    (summary,) = store.list_finished()
    assert (summary.id, summary.name_a, summary.name_b) == ("m1", "alice", "bob")
    assert (summary.winner, summary.reason) == (None, "decision")
    assert (summary.hp_a, summary.hp_b, summary.turn_count) == (100.0, 100.0, 1)
    assert store.get_log("m1") == log
    row = store.get_match("m1")
    assert row is not None and row.status == "finished"


def test_unfinished_matches_are_neither_listed_nor_replayable(database: str) -> None:
    store.create_match("queued", "alice", "bob")
    store.create_match("running", "alice", "bob")
    store.mark_running("running")
    store.create_match("failed", "alice", "bob")
    store.mark_failed("failed", "rate limited")

    assert store.list_finished() == []
    assert [store.get_log(i) for i in ("queued", "running", "failed")] == [None, None, None]


def test_failure_keeps_its_reason(database: str) -> None:
    store.create_match("m1", "alice", "bob")

    store.mark_failed("m1", "groq rate limited after 8 retries")

    row = store.get_match("m1")
    assert row is not None and row.ended_at is not None  # a failed match has ended too
    assert replace(row, ended_at=None) == store.MatchRow(
        "m1", "failed", "alice", "bob", "groq rate limited after 8 retries"
    )


def test_matches_left_running_by_a_dead_worker_are_failed(database: str) -> None:
    store.create_match("stuck", "alice", "bob")
    store.mark_running("stuck")
    store.create_match("waiting", "alice", "bob")

    assert store.fail_stale_running() == 1

    stuck, waiting = store.get_match("stuck"), store.get_match("waiting")
    assert stuck is not None and (stuck.status, stuck.error) == (
        "failed", "the worker stopped while this match was running"
    )  # fmt: skip
    assert waiting is not None and waiting.status == "queued"


def test_only_queued_matches_count_as_waiting(database: str) -> None:
    for name in ("a", "b", "c"):
        store.create_match(name, "alice", "bob")
    store.mark_running("c")

    assert store.count_queued() == 2


def test_import_keeps_what_it_is_given_and_skips_duplicates(
    database: str, sample_log: SampleLog
) -> None:
    log = sample_log("gemini-lite", "gpt-oss")
    summary = parse_replay("old-1", log).summary

    assert store.insert_finished("old-1", log, summary) is True
    assert store.insert_finished("old-1", log, summary) is False

    (listed,) = store.list_finished()
    assert (listed.id, listed.name_a, listed.name_b) == ("old-1", "gemini-lite", "gpt-oss")


def test_migrating_twice_changes_nothing(database: str) -> None:
    migrate()
    migrate()

    with psycopg.connect(database_url()) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations")]
    assert names == sorted(p.name for p in MIGRATIONS.glob("*.sql"))


def test_connections_come_from_one_bounded_pool(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every request used to open its own connection, so a flood could use them all up (D-070).
    monkeypatch.setenv("ARENA_DB_POOL", "2")
    monkeypatch.setattr(store, "POOL_WAIT_S", 0.3)

    with store.connect() as one, store.connect() as two:
        assert one is not two
        with pytest.raises(PoolTimeout), store.connect():
            pass  # a third has to wait, and gives up

    with store.connect() as again:  # connections come back to the pool
        assert again.execute("SELECT 1 AS n").fetchone() == {"n": 1}


def test_a_busy_pool_answers_503_not_500(
    database: str, monkeypatch: pytest.MonkeyPatch, queue: StubQueue
) -> None:
    monkeypatch.setenv("ARENA_DB_POOL", "1")
    monkeypatch.setattr(store, "POOL_WAIT_S", 0.3)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, "not-a-real-session")  # a session check needs the database

    with store.connect():  # the only connection is taken
        busy = client.get("/auth/me")

    assert busy.status_code == 503 and "busy" in busy.json()["detail"]
    assert busy.headers["retry-after"] == "5"
    assert client.get("/auth/me").status_code == 401  # free again: a plain "not signed in"


def test_a_pooled_connection_still_commits_at_the_end_and_rolls_back_on_an_error(
    database: str,
) -> None:
    store.create_match("m1", "alice", "bob")

    with pytest.raises(RuntimeError), store.connect() as conn:
        conn.execute("UPDATE matches SET status = 'failed' WHERE id = 'm1'")
        raise RuntimeError("boom")

    row = store.get_match("m1")
    assert row is not None and row.status == "queued"  # rolled back
    with store.connect() as conn:
        conn.execute("UPDATE matches SET status = 'running' WHERE id = 'm1'")
    row = store.get_match("m1")
    assert row is not None and row.status == "running"  # committed
