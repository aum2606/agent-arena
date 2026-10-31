import json
from collections.abc import Callable

import httpx2
import pytest

from arena.config import ConfigError, Provider, Settings
from arena.llm import LlmClient, LlmError, LlmTimeout
from arena.models import Fighter

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    snippet_timeout_s=5.0,
    call_delay_s=2.0,
    max_retries=2,
    backoff_base_s=1.0,
)
PROVIDERS = {"groq": Provider("https://groq.test/v1", "GROQ_API_KEY")}
FIGHTER = Fighter("alpha", "groq", "some-model", "persona")


def chat_response(content: str | None = "hello", finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "some-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


def rate_limited() -> httpx2.Response:
    return httpx2.Response(429, json={"error": {"message": "slow down"}})


class Harness:
    def __init__(self, handler: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self.sleeps: list[float] = []

        def record(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            return handler(request)

        self.client = LlmClient(
            PROVIDERS,
            SETTINGS,
            http_client=httpx2.Client(transport=httpx2.MockTransport(record)),
            sleep=self.sleeps.append,
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> type[Harness]:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    return Harness


def test_routes_request_to_the_fighters_provider_and_model(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response("hi"))

    completion = h.client.complete(FIGHTER, "be nice", "say hi")

    assert (completion.text, completion.truncated) == ("hi", False)
    (request,) = h.requests
    assert str(request.url) == "https://groq.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "some-model"
    assert body["max_tokens"] == 256
    assert body["messages"] == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "say hi"},
    ]


def test_waits_the_configured_delay_after_a_call(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response())
    h.client.complete(FIGHTER, "s", "u")
    assert h.sleeps == [2.0]


def test_length_finish_reason_is_reported_as_truncated(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response("cut off", finish_reason="length"))
    assert h.client.complete(FIGHTER, "s", "u").truncated


def test_null_content_becomes_empty_text(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response(None))
    assert h.client.complete(FIGHTER, "s", "u").text == ""


def test_retries_429_with_exponential_backoff_and_jitter(harness: type[Harness]) -> None:
    responses = [rate_limited(), rate_limited(), chat_response("finally")]
    h = harness(lambda _: responses.pop(0))

    completion = h.client.complete(FIGHTER, "s", "u")

    assert completion.text == "finally"
    first, second, delay = h.sleeps
    assert 0.5 <= first <= 1.5
    assert 1.0 <= second <= 3.0
    assert delay == 2.0


def test_gives_up_after_max_retries(harness: type[Harness]) -> None:
    h = harness(lambda _: rate_limited())

    with pytest.raises(LlmError, match="rate limited"):
        h.client.complete(FIGHTER, "s", "u")

    assert len(h.requests) == SETTINGS.max_retries + 1
    assert len(h.sleeps) == SETTINGS.max_retries


def test_timeout_is_its_own_error(harness: type[Harness]) -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(LlmTimeout):
        harness(slow).client.complete(FIGHTER, "s", "u")


def test_client_errors_fail_without_retrying(harness: type[Harness]) -> None:
    h = harness(lambda _: httpx2.Response(400, json={"error": {"message": "bad request"}}))

    with pytest.raises(LlmError, match="400"):
        h.client.complete(FIGHTER, "s", "u")

    assert len(h.requests) == 1


def unavailable() -> httpx2.Response:
    return httpx2.Response(503, json={"error": {"message": "overloaded"}})


def test_retries_503_with_backoff(harness: type[Harness]) -> None:
    responses = [unavailable(), unavailable(), chat_response("back up")]
    h = harness(lambda _: responses.pop(0))

    assert h.client.complete(FIGHTER, "s", "u").text == "back up"
    assert len(h.requests) == 3
    first, second, delay = h.sleeps
    assert 0.5 <= first <= 1.5
    assert 1.0 <= second <= 3.0
    assert delay == 2.0


def test_gives_up_on_persistent_server_errors(harness: type[Harness]) -> None:
    h = harness(lambda _: unavailable())

    with pytest.raises(LlmError, match="HTTP 503"):
        h.client.complete(FIGHTER, "s", "u")

    assert len(h.requests) == SETTINGS.max_retries + 1
    assert len(h.sleeps) == SETTINGS.max_retries


def test_response_without_choices_is_an_error(harness: type[Harness]) -> None:
    h = harness(lambda _: httpx2.Response(200, json={"choices": []}))
    with pytest.raises(LlmError, match="no choices"):
        h.client.complete(FIGHTER, "s", "u")


def test_missing_api_key_names_the_variable(
    harness: type[Harness], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        harness(lambda _: chat_response()).client.complete(FIGHTER, "s", "u")
