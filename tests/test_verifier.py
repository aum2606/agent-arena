from pathlib import Path

import pytest

from arena.verifier import answers_match, verify_attack

TIMEOUT_S = 5.0


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("42", " 42 "),
        ("1/2", "0.5"),
        ("sqrt(8)", "2*sqrt(2)"),
        ("x**2 - 1", "(x - 1)*(x + 1)"),
        ("x^2", "x**2"),
        ("100*arcsin(3/5) - 48", "100*asin(3/5) - 48"),
        ("arccos(1/2)", "pi/3"),
        ("arctan(1)", "pi/4"),
    ],
)
def test_answers_match_equal(a: str, b: str) -> None:
    assert answers_match(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [("3", "4"), ("x + 1", "x + 2"), ("", "1"), ("2 +", "2"), ("not an answer(", "1")],
)
def test_answers_match_different_or_unparseable(a: str, b: str) -> None:
    assert not answers_match(a, b)


def test_verify_passes_when_snippet_output_matches() -> None:
    result = verify_attack("42", "print(2 * 21)", TIMEOUT_S)
    assert result.passed


def test_verify_matches_symbolically() -> None:
    assert verify_attack("1/2", "print(0.5)", TIMEOUT_S).passed


def test_verify_fails_on_wrong_output() -> None:
    result = verify_attack("42", "print(41)", TIMEOUT_S)
    assert not result.passed
    assert "mismatch" in result.reason


def test_verify_fails_on_error() -> None:
    result = verify_attack("42", "raise ValueError('boom')", TIMEOUT_S)
    assert not result.passed
    assert "boom" in result.reason


def test_verify_fails_on_no_output() -> None:
    assert not verify_attack("42", "x = 42", TIMEOUT_S).passed


def test_verify_fails_on_timeout() -> None:
    result = verify_attack("42", "while True: pass", 0.5)
    assert not result.passed
    assert "timeout" in result.reason


def test_snippet_does_not_see_secret_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    code = "import os; print(len(os.environ.get('OPENROUTER_API_KEY', '')))"
    assert verify_attack("0", code, TIMEOUT_S).passed


def test_snippet_runs_in_its_own_temp_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    code = "import os; print(int(os.path.exists('marker.txt')))"
    assert verify_attack("0", code, TIMEOUT_S).passed
