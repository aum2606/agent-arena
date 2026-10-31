import logging
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx2
import openai

from arena.config import ConfigError, Provider, Settings
from arena.models import Fighter

logger = logging.getLogger(__name__)


class LlmError(Exception):
    pass


class LlmTimeout(LlmError):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    truncated: bool  # hit the token cap


class LlmClient:
    """One OpenAI-compatible client per provider, with 429 backoff and a delay between calls."""

    def __init__(
        self,
        providers: dict[str, Provider],
        settings: Settings,
        http_client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._providers = providers
        self._settings = settings
        self._http_client = http_client
        self._sleep = sleep
        self._clients: dict[str, openai.OpenAI] = {}

    def complete(self, fighter: Fighter, system: str, user: str) -> Completion:
        client = self._client(fighter.provider)
        s = self._settings
        for attempt in range(s.max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=fighter.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=s.turn_max_tokens,
                    timeout=s.turn_time_limit_s,
                )
            except (openai.RateLimitError, openai.InternalServerError) as exc:
                # 429 and 5xx (e.g. Gemini 503 "overloaded") are transient: back off and retry.
                problem = "rate limited" if exc.status_code == 429 else f"HTTP {exc.status_code}"
                if attempt == s.max_retries:
                    raise LlmError(
                        f"{fighter.provider} {problem} after {s.max_retries} retries"
                    ) from exc
                delay = s.backoff_base_s * 2**attempt * random.uniform(0.5, 1.5)
                logger.warning("%s %s, retrying in %.1fs", fighter.provider, problem, delay)
                self._sleep(delay)
            except openai.APITimeoutError as exc:
                raise LlmTimeout(f"{fighter.provider} timed out") from exc
            except openai.APIConnectionError as exc:
                raise LlmError(f"cannot reach {fighter.provider}: {exc}") from exc
            except openai.APIStatusError as exc:
                raise LlmError(
                    f"{fighter.provider} returned HTTP {exc.status_code}: {exc.message}"
                ) from exc
            else:
                break
        if not response.choices:
            raise LlmError(f"{fighter.provider} returned no choices")
        self._sleep(s.call_delay_s)
        choice = response.choices[0]
        return Completion(choice.message.content or "", choice.finish_reason == "length")

    def _client(self, provider: str) -> openai.OpenAI:
        if provider not in self._clients:
            spec = self._providers[provider]
            key = os.environ.get(spec.api_key_env)
            if not key:
                raise ConfigError(f"{spec.api_key_env} is not set (see .env.example)")
            # max_retries=0: retrying is handled here so the limit and backoff are configurable.
            self._clients[provider] = openai.OpenAI(
                base_url=spec.base_url,
                api_key=key,
                max_retries=0,
                http_client=self._http_client,
            )
        return self._clients[provider]
