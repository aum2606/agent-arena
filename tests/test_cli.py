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
        if user.endswith(ATTACK_REQUEST):
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


def sim(config_path: Path, out: Path, n: int) -> int:
    return main(["sim", "--n", str(n), "--config", str(config_path), "--out", str(out)])


def test_sim_saves_each_match_and_prints_stats(
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "LlmClient", StubClient)
    out = tmp_path / "sim.jsonl"

    code = sim(config_path, out, 2)

    text = capsys.readouterr().out
    assert code == 0
    assert "[1/2]" in text
    assert "[2/2]" in text
    assert "Matches: 2, turns: 12" in text
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2
    assert sorted(p.name for p in (tmp_path / "runs" / "logs").glob("*.json")) == [
        "sim_0000.json",
        "sim_0001.json",
    ]


def test_sim_resumes_from_saved_matches(
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "LlmClient", StubClient)
    out = tmp_path / "sim.jsonl"
    sim(config_path, out, 1)
    capsys.readouterr()

    code = sim(config_path, out, 2)

    text = capsys.readouterr().out
    assert code == 0
    assert "[1/2]" not in text
    assert "[2/2]" in text
    assert "Matches: 2" in text
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_sim_with_enough_saved_matches_runs_nothing(
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "LlmClient", StubClient)
    out = tmp_path / "sim.jsonl"
    sim(config_path, out, 1)
    capsys.readouterr()

    assert sim(config_path, out, 1) == 0

    text = capsys.readouterr().out
    assert "[" not in text.split("Matches:")[0]
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_sim_rejects_non_positive_n(
    config_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sim(config_path, tmp_path / "sim.jsonl", 0) == 1
    assert "--n" in capsys.readouterr().err


def test_sim_needs_two_fighters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    path = tmp_path / "one.toml"
    path.write_text(CONFIG[: CONFIG.index('[[fighters]]\nname = "bob"')], encoding="utf-8")

    assert sim(path, tmp_path / "sim.jsonl", 1) == 1
    assert "at least 2 fighters" in capsys.readouterr().err


def test_sim_provider_failure_stops_and_keeps_nothing_unfinished(
    config_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "LlmClient", FailingClient)
    out = tmp_path / "sim.jsonl"

    assert sim(config_path, out, 3) == 1
    assert "rate limited" in capsys.readouterr().err
    assert not out.exists()


def test_sim_reports_a_damaged_results_file(
    config_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "sim.jsonl"
    out.write_text('{"fighter_a": "al', encoding="utf-8")

    assert sim(config_path, out, 1) == 1
    assert "sim.jsonl:1" in capsys.readouterr().err


def test_synth_prints_the_sweep_table(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["synth", "--matches", "2"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Attacker win rate" in out
    assert "gate passes" in out
