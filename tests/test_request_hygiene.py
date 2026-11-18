"""What goes to the models, what reaches the logs, what config and sign-in refuse (D-080)."""

import json
import logging
import os
import random
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from helpers import FIGHTER as FIGHTER_BODY
from helpers import SignIn, StubQueue
from test_llm import FIGHTER, PROVIDERS, SETTINGS, chat_response

from arena.battle_log import BattleLog
from arena.config import ConfigError, load_config
from arena.llm import LlmClient
from arena.models import Fighter
from arena.orchestrator import run_match
from arena.prompts import attack_prompts, defense_prompts, unparsed_prompt
from arena_api import auth
from arena_api.app import app

HIDDEN = chr(0x202E) + chr(0x200B)  # a right-to-left override and a zero-width space


def sent_to_the_model(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_provider_key")
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return chat_response("<answer>1</answer>")

    client = LlmClient(
        PROVIDERS,
        SETTINGS,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        sleep=lambda _: None,
    )
    client.complete(FIGHTER, "system text", "user text", 100)
    body: dict[str, object] = json.loads(seen[0].content)
    return body


def test_a_request_to_a_model_offers_no_tools_and_carries_only_the_two_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = sent_to_the_model(monkeypatch)

    # A model that obeys an injected instruction can only write text: there is nothing to call.
    for tool in ("tools", "tool_choice", "functions", "function_call", "web_search_options"):
        assert tool not in body
    messages = body["messages"]
    assert isinstance(messages, list)
    assert [m["role"] for m in messages] == ["system", "user"]


def test_no_prompt_has_a_place_for_a_key() -> None:
    fighter = Fighter("alpha", "groq", "m", "persona text")
    secret = "gsk_secret_provider_key"
    attack = attack_prompts(fighter, "algebra", ["an earlier problem"])
    code_attack = attack_prompts(fighter, "strings", [], domain="code")
    prompts = [
        *attack,
        *code_attack,
        *defense_prompts(fighter, "Compute 2+2."),
        *defense_prompts(fighter, "def solve(x): ...", "code"),
        unparsed_prompt(attack[1], True),
    ]

    assert not any(secret in p or "api_key" in p.lower() for p in prompts)


def test_a_defenders_answer_is_logged_without_hidden_characters() -> None:
    from test_orchestrator import A, B, FakeLlm, answer, good_attack

    llm = FakeLlm(
        attacks={"alice": [good_attack()] * 3, "bob": [good_attack()] * 3},
        defenses={"alice": [answer(f"4{HIDDEN}2")] * 3, "bob": [answer("0")] * 3},
    )

    log = BattleLog("m1")
    run_match(A, B, llm, SETTINGS, log, random.Random(0))

    events = [
        e for t in log.to_dict()["turns"] for e in t["events"] if e["type"] == "defend_result"
    ]
    answers = [e["answer"] for e in events]
    assert "42" in answers and all(HIDDEN not in a for a in answers if a)


def test_a_retried_attempt_is_logged_without_hidden_characters() -> None:
    from test_orchestrator import A, B, FakeLlm, answer, good_attack

    wrong_first = good_attack(problem=f"What is 4{HIDDEN}2?", answer="41", code="print(42)")
    llm = FakeLlm(
        attacks={
            "alice": [wrong_first, good_attack(), good_attack(), good_attack()],
            "bob": [good_attack()] * 3,
        },
        defenses={"alice": [answer("42")] * 3, "bob": [answer("42")] * 3},
    )

    log = BattleLog("m1")
    run_match(A, B, llm, SETTINGS, log, random.Random(0))

    retries = [
        e for t in log.to_dict()["turns"] for e in t["events"] if e["type"] == "attack_retry"
    ]
    assert [e["problem"] for e in retries] == ["What is 42?"]


def settings_toml(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "fighters.toml"
    path.write_text(
        "[settings]\nturn_time_limit_s = 60.0\nturn_max_tokens = 1024\ndefender_max_tokens = 512\n"
        "snippet_timeout_s = 5.0\ncall_delay_s = 0.0\nmax_retries = 1\nbackoff_base_s = 1.0\n"
        f'{extra}\n[providers.groq]\nbase_url = "https://example.test/v1"\napi_key_env = "G"\n',
        encoding="utf-8",
    )
    return path


def test_blocked_terms_come_from_the_deployers_config(tmp_path: Path) -> None:
    config = load_config(settings_toml(tmp_path, 'blocked_terms = ["frobnicate", "bad phrase"]'))

    assert config.settings.blocked_terms == ("frobnicate", "bad phrase")
    assert load_config(settings_toml(tmp_path, "")).settings.blocked_terms == ()


@pytest.mark.parametrize(
    "bad", ['blocked_terms = [""]', 'blocked_terms = ["a' + "b" * 120 + '"]', "blocked_terms = [3]"]
)
def test_a_malformed_blocked_term_is_refused_at_load(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="blocked_terms"):
        load_config(settings_toml(tmp_path, bad))


def dev_client(monkeypatch: pytest.MonkeyPatch, queue: StubQueue) -> TestClient:
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")
    monkeypatch.setenv("PUBLIC_URL", "http://127.0.0.1:3100")
    return TestClient(app)


@pytest.mark.parametrize(
    "headers",
    [
        {"x-forwarded-for": "203.0.113.5"},
        {"x-forwarded-for": "127.0.0.1, 198.51.100.9"},
        {"cf-connecting-ip": "8.8.8.8"},
        {"x-real-ip": "203.0.113.5"},
        {"tailscale-funnel-request": "?1"},
        {"forwarded": "for=203.0.113.5;proto=https"},
    ],
)
def test_dev_login_is_refused_for_a_request_that_came_through_a_tunnel_or_proxy(
    monkeypatch: pytest.MonkeyPatch, queue: StubQueue, headers: dict[str, str]
) -> None:
    client = dev_client(monkeypatch, queue)

    refused = client.post("/auth/dev", json={"handle": "mallory"}, headers=headers)
    config = client.get("/auth/config", headers=headers).json()

    assert refused.status_code == 404
    assert config["dev_login"] is False


def test_dev_login_still_works_for_a_request_from_this_machine(
    monkeypatch: pytest.MonkeyPatch, queue: StubQueue
) -> None:
    client = dev_client(monkeypatch, queue)

    assert client.get("/auth/config", headers={"x-forwarded-for": "127.0.0.1"}).json()["dev_login"]
    assert client.get("/auth/config").json()["dev_login"] is True


def test_starting_with_dev_login_on_says_so_loudly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ARENA_DEV_LOGIN", "1")
    monkeypatch.setenv("PUBLIC_URL", "http://127.0.0.1:3100")

    with caplog.at_level(logging.WARNING):
        auth.warn_if_dev_login()

    assert "sign in as any handle" in caplog.text
    caplog.clear()
    monkeypatch.delenv("ARENA_DEV_LOGIN")
    auth.warn_if_dev_login()
    assert caplog.text == ""


def test_a_fighter_with_a_blocked_term_is_refused_without_repeating_it(
    sign_in: SignIn, config_file: object, encryption: None, queue: StubQueue
) -> None:
    path = Path(os.environ["FIGHTERS_CONFIG"])
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "backoff_base_s = 0.0", 'backoff_base_s = 0.0\nblocked_terms = ["frobnicate"]'
        ),
        encoding="utf-8",
    )
    client = sign_in("ada")

    persona = client.post("/fighters", json=FIGHTER_BODY | {"persona": "I frobnicate everyone"})
    name = client.post("/fighters", json=FIGHTER_BODY | {"name": "frobnicate"})
    ok = client.post("/fighters", json=FIGHTER_BODY)

    assert (persona.status_code, name.status_code, ok.status_code) == (422, 422, 201)
    assert "frobnicate" not in persona.text and "persona" in persona.json()["detail"]
    edit = {"provider": "groq", "model": "m", "persona": "frobnicate!"}
    assert client.post(f"/fighters/{ok.json()['id']}/versions", json=edit).status_code == 422
