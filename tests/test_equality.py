import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from arena import equality
from arena.equality import symbolic_equal

EXPLOIT = "(x+1)**200*(x+2)**200*(x+3)**200"  # 32 characters; simplify() ran for over 25 s on it


def helper_pid() -> int | None:
    process = equality._helper._process
    return process.pid if process else None


def test_equal_and_unequal_values() -> None:
    assert symbolic_equal("sqrt(8)", "2*sqrt(2)")
    assert symbolic_equal("1/2", "0.5")
    assert symbolic_equal("(x - 1)*(x + 1)", "x**2 - 1")
    assert not symbolic_equal("3", "4")
    assert not symbolic_equal("x + 1", "x + 2")


def test_refused_or_unparseable_text_is_just_not_equal() -> None:
    assert not symbolic_equal("__import__('os')", "1")
    assert not symbolic_equal("9**9**9", "1")
    assert not symbolic_equal("2 +", "2")


def test_one_helper_process_serves_every_comparison() -> None:
    symbolic_equal("1", "1")
    first = helper_pid()

    symbolic_equal("2", "2")
    symbolic_equal("3", "4")

    assert first is not None and helper_pid() == first


def test_a_comparison_that_runs_too_long_is_not_equal_and_the_helper_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbolic_equal("1", "1")
    before = helper_pid()
    monkeypatch.setattr(equality, "TIMEOUT_S", 2.0)

    start = time.monotonic()
    result = symbolic_equal(EXPLOIT, "1")
    elapsed = time.monotonic() - start

    assert result is False and elapsed < 8
    assert symbolic_equal("1/2", "0.5")  # a fresh helper answers the next one
    assert helper_pid() != before


def test_a_helper_that_died_is_replaced() -> None:
    symbolic_equal("1", "1")
    process = equality._helper._process
    assert process is not None
    process.kill()
    process.wait()

    assert symbolic_equal("sqrt(8)", "2*sqrt(2)")


def test_threads_can_compare_at_the_same_time() -> None:
    results: list[bool] = []

    def compare(i: int) -> None:
        results.append(symbolic_equal(f"{i} + 1", f"{i + 1}"))

    threads = [threading.Thread(target=compare, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [True] * 8


def test_a_script_file_without_a_main_guard_can_use_it(tmp_path: Path) -> None:
    # multiprocessing's spawn re-runs the main script file in the child, which broke such scripts.
    script = tmp_path / "no_guard.py"
    script.write_text(
        "from arena.equality import symbolic_equal\n"
        "print('result:', symbolic_equal('sqrt(8)', '2*sqrt(2)'), flush=True)\n",
        encoding="utf-8",
    )

    done = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )

    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.strip() == "result: True"


def test_the_helper_does_not_inherit_the_workers_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "secret-that-must-not-leak")
    equality._helper.stop()  # the next comparison starts a helper under this environment

    assert symbolic_equal("1", "1")

    assert equality._helper._process is not None
    environment = equality._helper_environment()
    assert "GROQ_API_KEY" not in environment and "DATABASE_URL" not in environment
