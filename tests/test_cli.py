from pathlib import Path

import pytest

from arena import cli
from arena.cli import format_summary, main
from arena.config import Provider, Settings
from arena.llm import Completion, LlmError
from arena.models import Fighter, MatchRecord, MatchResult, TurnResult
from arena.prompts import ATTACK_REQUEST

CONFIG = """
[settings]
turn_time_limit_s = 30.0
turn_max_tokens = 256
snippet_timeout_s = 5.0
call_delay_s = 0.0
max_retries = 0
backoff_base_s = 0.0

[providers.p]
base_url = "https://example.test/v1"
api_key_env = "P_API_KEY"

[[fighters]]
name = "alice"
provider = "p"
model = "m"
persona = "persona a"

[[fighters]]
name = "bob"
provider = "p"
model = "m"
persona = "persona b"
"""


class StubClient:
    """Stands in for LlmClient: attacks with 42, defends with 42 so every attack is blocked."""

    def __init__(self, providers: dict[str, Provider], settings: Settings) -> None:
        pass

    def complete(self, fighter: Fighter, system: str, user: str) -> Completion:
        if user == ATTACK_REQUEST:
            return Completion(
                "<problem>6 * 7?</problem><answer>42</answer><code>print(42)</code>", False
            )
        return Completion("<answer>42</answer>", False)


class FailingClient(StubClient):
    def complete(self, fighter: Fighter, system: str, user: str) -> Completion:
        raise LlmError("rate limited after 5 retries")


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    path = tmp_path / "fighters.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_match_prints_summary_and_saves_log(
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "LlmClient", StubClient)

    code = main(["match", "--a", "alice", "--b", "bob", "--config", str(config_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "alice (A) vs bob (B)" in out
    assert "Turn 6" in out
    assert "draw" in out
    (log_file,) = (tmp_path / "runs").glob("m_*.json")
    assert str(log_file) in out


def test_unknown_fighter_lists_available_names(
    config_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["match", "--a", "alice", "--b", "zed", "--config", str(config_path)])

    err = capsys.readouterr().err
    assert code == 1
    assert "zed" in err
    assert "alice, bob" in err


def test_provider_failure_exits_with_message(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "LlmClient", FailingClient)

    code = main(["match", "--a", "alice", "--b", "bob", "--config", str(config_path)])

    assert code == 1
    assert "rate limited after 5 retries" in capsys.readouterr().err


def test_bad_config_path_exits_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["match", "--a", "x", "--b", "y", "--config", str(tmp_path / "nope.toml")])

    assert code == 1
    assert "cannot read" in capsys.readouterr().err


def test_format_summary() -> None:
    record = MatchRecord(
        "alice",
        "bob",
        [
            TurnResult(1, "a", "hit", "b", 20.0),
            TurnResult(2, "b", "block", "a", 0.0),
            TurnResult(3, "a", "backfire", "a", 20.0),
        ],
        hp_a=80.0,
        hp_b=80.0,
        result=MatchResult("a", "ko"),
    )

    assert format_summary(record).splitlines() == [
        "alice (A) vs bob (B)",
        "Turn 1: alice attacks -> hit, bob takes 20 damage",
        "Turn 2: bob attacks -> block, alice takes 0 damage",
        "Turn 3: alice attacks -> backfire, alice takes 20 damage",
        "Final HP: alice 80, bob 80",
        "Result: alice wins by ko",
    ]
