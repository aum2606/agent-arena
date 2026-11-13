import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.models import Fighter


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    turn_time_limit_s: float
    turn_max_tokens: int
    defender_max_tokens: int
    snippet_timeout_s: float
    call_delay_s: float
    max_retries: int
    backoff_base_s: float
    code_share: float = 0.0  # chance that a turn is a code strike instead of math (D-045)
    attack_retries: int = 1  # how many corrections a failed attack gets before it backfires (D-062)


@dataclass(frozen=True)
class Provider:
    base_url: str
    api_key_env: str


@dataclass(frozen=True)
class Config:
    settings: Settings
    providers: dict[str, Provider]
    fighters: dict[str, Fighter]
    house_bot: str | None = None  # the fighter users spar against
    panel: tuple[Fighter, ...] = ()  # reference solvers that score problem difficulty (D-036)


def _build[T](cls: type[T], raw: Any, what: str) -> T:
    try:
        return cls(**raw)
    except TypeError as exc:
        raise ConfigError(f"invalid {what}: {exc}") from exc


def load_config(path: Path) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    settings = _build(Settings, data.get("settings", {}), "[settings]")
    if not 0.0 <= settings.code_share <= 1.0:
        raise ConfigError(f"code_share must be between 0 and 1, not {settings.code_share}")
    if settings.attack_retries < 0:
        raise ConfigError(f"attack_retries cannot be negative, not {settings.attack_retries}")
    providers = {
        name: _build(Provider, raw, f"provider {name!r}")
        for name, raw in data.get("providers", {}).items()
    }
    fighters: dict[str, Fighter] = {}
    for raw in data.get("fighters", []):
        fighter = _build(Fighter, raw, "fighter")
        if fighter.provider not in providers:
            raise ConfigError(f"fighter {fighter.name!r} has unknown provider {fighter.provider!r}")
        if fighter.name in fighters:
            raise ConfigError(f"duplicate fighter {fighter.name!r}")
        fighters[fighter.name] = fighter
    house_bot = data.get("house_bot")
    if house_bot is not None and house_bot not in fighters:
        raise ConfigError(f"house_bot {house_bot!r} is not one of the configured fighters")
    panel: list[Fighter] = []
    for raw in data.get("panel", []):
        member = _build(Fighter, raw, "panel member")
        if member.provider not in providers:
            raise ConfigError(
                f"panel member {member.name!r} has unknown provider {member.provider!r}"
            )
        if any(member.name == other.name for other in panel):
            raise ConfigError(f"duplicate panel member {member.name!r}")
        panel.append(member)
    return Config(settings, providers, fighters, house_bot, tuple(panel))
