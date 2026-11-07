from pathlib import Path

import pytest

from arena.config import ConfigError, load_config
from arena.models import Fighter

VALID = """
[settings]
turn_time_limit_s = 60.0
turn_max_tokens = 1024
defender_max_tokens = 512
snippet_timeout_s = 5.0
call_delay_s = 2.0
max_retries = 5
backoff_base_s = 2.0

[providers.groq]
base_url = "https://example.test/v1"
api_key_env = "GROQ_API_KEY"

[[fighters]]
name = "alpha"
provider = "groq"
model = "some-model"
persona = "You are cunning."
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "fighters.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))

    assert config.settings.max_retries == 5
    assert config.settings.turn_time_limit_s == 60.0
    assert config.settings.snippet_timeout_s == 5.0
    assert (config.settings.turn_max_tokens, config.settings.defender_max_tokens) == (1024, 512)
    assert config.providers["groq"].api_key_env == "GROQ_API_KEY"
    assert config.providers["groq"].base_url == "https://example.test/v1"
    assert config.fighters["alpha"] == Fighter("alpha", "groq", "some-model", "You are cunning.")
    assert config.fighters["alpha"].persona == "You are cunning."


def test_shipped_config_parses() -> None:
    config = load_config(Path(__file__).parents[1] / "config" / "fighters.toml")
    assert len(config.fighters) >= 2  # `arena sim` needs a pair


def test_gate_pool_config_parses() -> None:
    config = load_config(Path(__file__).parents[1] / "config" / "gate-groq.toml")
    assert set(config.fighters) == {"gpt-oss", "qwen"}


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(write(tmp_path, "[settings"))


def test_missing_setting(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="settings"):
        load_config(write(tmp_path, VALID.replace("max_retries = 5\n", "")))


def test_unknown_provider_on_fighter(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown provider 'nowhere'"):
        load_config(write(tmp_path, VALID.replace('provider = "groq"', 'provider = "nowhere"')))


def test_duplicate_fighter_name(tmp_path: Path) -> None:
    fighter = VALID[VALID.index("[[fighters]]") :]
    with pytest.raises(ConfigError, match="duplicate fighter 'alpha'"):
        load_config(write(tmp_path, VALID + fighter))


def test_fighter_missing_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="fighter"):
        load_config(write(tmp_path, VALID.replace('model = "some-model"\n', "")))


def test_house_bot_names_a_fighter_and_is_optional(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, VALID)).house_bot is None

    config = load_config(write(tmp_path, 'house_bot = "alpha"\n' + VALID))

    assert config.house_bot == "alpha"


def test_house_bot_must_be_a_configured_fighter(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="house_bot"):
        load_config(write(tmp_path, 'house_bot = "nobody"\n' + VALID))


PANEL = """
[[panel]]
name = "ref-1"
provider = "groq"
model = "model-1"
persona = "a careful solver"

[[panel]]
name = "ref-2"
provider = "groq"
model = "model-2"
persona = "a careful solver"
"""


def test_panel_is_a_list_of_reference_solvers_and_optional(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, VALID)).panel == ()

    config = load_config(write(tmp_path, VALID + PANEL))

    assert [m.name for m in config.panel] == ["ref-1", "ref-2"]
    assert config.panel[1] == Fighter("ref-2", "groq", "model-2", "a careful solver")


def test_panel_members_need_a_known_provider_and_unique_names(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown provider 'nowhere'"):
        load_config(
            write(tmp_path, VALID + PANEL.replace('provider = "groq"', 'provider = "nowhere"'))
        )
    with pytest.raises(ConfigError, match="duplicate panel member 'ref-1'"):
        load_config(write(tmp_path, VALID + PANEL.replace("ref-2", "ref-1")))


def test_code_share_defaults_to_math_only_and_can_be_set(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, VALID)).settings.code_share == 0.0
    shared = VALID.replace("max_retries = 5\n", "max_retries = 5\ncode_share = 0.25\n")

    assert load_config(write(tmp_path, shared)).settings.code_share == 0.25


@pytest.mark.parametrize("value", ["-0.1", "1.5"])
def test_code_share_is_a_share(tmp_path: Path, value: str) -> None:
    text = VALID.replace("max_retries = 5\n", f"max_retries = 5\ncode_share = {value}\n")

    with pytest.raises(ConfigError, match="code_share"):
        load_config(write(tmp_path, text))
