import json
from collections.abc import Callable

import httpx2
import pytest

from arena.config import ConfigError, Provider, Settings
from arena.llm import LlmClient, LlmError, LlmTimeout, LlmUnavailable
from arena.models import Fighter

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    defender_max_tokens=128,
    snippet_timeout_s=5.0,
    call_delay_s=2.0,
    max_retries=2,
    backoff_base_s=1.0,
)
PROVIDERS = {"groq": Provider("https://groq.test/v1", "GROQ_API_KEY")}
FIGHTER = Fighter("alpha", "groq", "some-model", "persona")


def chat_response(
    content: str | None = "hello",
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            **({"usage": usage} if usage else {}),
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

    completion = h.client.complete(FIGHTER, "be nice", "say hi", 64)

    assert (completion.text, completion.truncated) == ("hi", False)
    (request,) = h.requests
    assert str(request.url) == "https://groq.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "some-model"
    assert body["max_tokens"] == 64  # the caller's cap, not a setting
    assert body["messages"] == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "say hi"},
    ]


def test_waits_the_configured_delay_after_a_call(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response())
    h.client.complete(FIGHTER, "s", "u", 64)
    assert h.sleeps == [2.0]


def test_length_finish_reason_is_reported_as_truncated(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response("cut off", finish_reason="length"))
    assert h.client.complete(FIGHTER, "s", "u", 64).truncated


def test_null_content_becomes_empty_text(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response(None))
    assert h.client.complete(FIGHTER, "s", "u", 64).text == ""


def test_retries_429_with_exponential_backoff_and_jitter(harness: type[Harness]) -> None:
    responses = [rate_limited(), rate_limited(), chat_response("finally")]
    h = harness(lambda _: responses.pop(0))

    completion = h.client.complete(FIGHTER, "s", "u", 64)

    assert completion.text == "finally"
    first, second, delay = h.sleeps
    assert 0.5 <= first <= 1.5
    assert 1.0 <= second <= 3.0
    assert delay == 2.0


def test_gives_up_after_max_retries(harness: type[Harness]) -> None:
    h = harness(lambda _: rate_limited())

    with pytest.raises(LlmError, match="rate limited"):
        h.client.complete(FIGHTER, "s", "u", 64)

    assert len(h.requests) == SETTINGS.max_retries + 1
    assert len(h.sleeps) == SETTINGS.max_retries


def test_timeout_is_its_own_error(harness: type[Harness]) -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(LlmTimeout):
        harness(slow).client.complete(FIGHTER, "s", "u", 64)


def test_client_errors_fail_without_retrying(harness: type[Harness]) -> None:
    h = harness(lambda _: httpx2.Response(400, json={"error": {"message": "bad request"}}))

    with pytest.raises(LlmError, match="400"):
        h.client.complete(FIGHTER, "s", "u", 64)

    assert len(h.requests) == 1


def unavailable() -> httpx2.Response:
    return httpx2.Response(503, json={"error": {"message": "overloaded"}})


def test_retries_503_with_backoff(harness: type[Harness]) -> None:
    responses = [unavailable(), unavailable(), chat_response("back up")]
    h = harness(lambda _: responses.pop(0))

    assert h.client.complete(FIGHTER, "s", "u", 64).text == "back up"
    assert len(h.requests) == 3
    first, second, delay = h.sleeps
    assert 0.5 <= first <= 1.5
    assert 1.0 <= second <= 3.0
    assert delay == 2.0


def test_gives_up_on_persistent_server_errors(harness: type[Harness]) -> None:
    h = harness(lambda _: unavailable())

    with pytest.raises(LlmError, match="HTTP 503"):
        h.client.complete(FIGHTER, "s", "u", 64)

    assert len(h.requests) == SETTINGS.max_retries + 1
    assert len(h.sleeps) == SETTINGS.max_retries


def test_response_without_choices_is_an_error(harness: type[Harness]) -> None:
    h = harness(lambda _: httpx2.Response(200, json={"choices": []}))
    with pytest.raises(LlmError, match="no choices"):
        h.client.complete(FIGHTER, "s", "u", 64)


def test_missing_api_key_names_the_variable(
    harness: type[Harness], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        harness(lambda _: chat_response()).client.complete(FIGHTER, "s", "u", 64)


def _client_with_keys(requests: list[httpx2.Request], keys: dict[str, str]) -> LlmClient:
    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return chat_response()

    return LlmClient(
        PROVIDERS,
        SETTINGS,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
        sleep=lambda _: None,
        keys=keys,
    )


def test_a_fighters_own_key_is_used_and_others_still_get_the_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "server-key")
    requests: list[httpx2.Request] = []
    client = _client_with_keys(requests, {"alpha": "their-key"})

    client.complete(FIGHTER, "s", "u", 64)
    client.complete(Fighter("beta", "groq", "some-model", "persona"), "s", "u", 64)

    assert [r.headers["authorization"] for r in requests] == [
        "Bearer their-key",
        "Bearer server-key",
    ]


def test_a_fighters_own_key_works_when_the_server_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    requests: list[httpx2.Request] = []

    _client_with_keys(requests, {"alpha": "their-key"}).complete(FIGHTER, "s", "u", 64)

    assert requests[0].headers["authorization"] == "Bearer their-key"


def test_the_providers_token_count_is_kept_when_it_reports_one(harness: type[Harness]) -> None:
    usage = {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}
    h = harness(lambda _: chat_response("hi", usage=usage))

    assert h.client.complete(FIGHTER, "s", "u", 64).tokens == 42


def test_the_token_count_is_none_when_the_provider_does_not_report_it(
    harness: type[Harness],
) -> None:
    h = harness(lambda _: chat_response("hi"))

    assert h.client.complete(FIGHTER, "s", "u", 64).tokens is None


def test_output_tokens_count_everything_after_the_prompt_including_hidden_reasoning(
    harness: type[Harness],
) -> None:
    # Gemini's completion_tokens leaves out its thinking; total minus prompt is what a cap limits.
    usage = {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 100}
    h = harness(lambda _: chat_response("hi", usage=usage))

    completion = h.client.complete(FIGHTER, "s", "u", 64)

    assert (completion.tokens, completion.output_tokens) == (100, 70)


def test_output_tokens_are_none_without_usage(harness: type[Harness]) -> None:
    h = harness(lambda _: chat_response("hi"))

    assert h.client.complete(FIGHTER, "s", "u", 64).output_tokens is None


def test_running_out_of_retries_on_a_busy_provider_is_unavailable_not_just_an_error(
    harness: type[Harness],
) -> None:
    h = harness(lambda _: rate_limited())

    with pytest.raises(LlmUnavailable, match="rate limited"):
        h.client.complete(FIGHTER, "s", "u", 64)


def test_a_provider_that_cannot_be_reached_is_unavailable(harness: type[Harness]) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(LlmUnavailable, match="cannot reach groq"):
        harness(down).client.complete(FIGHTER, "s", "u", 64)


def test_a_rejected_request_is_a_plain_error_that_waiting_would_not_fix(
    harness: type[Harness],
) -> None:
    h = harness(lambda _: httpx2.Response(401, json={"error": {"message": "bad key"}}))

    with pytest.raises(LlmError) as raised:
        h.client.complete(FIGHTER, "s", "u", 64)

    assert not isinstance(raised.value, LlmUnavailable)
