import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arena import sandbox
from arena.config import ConfigError
from arena.sandbox import MAX_OUTPUT_BYTES, ensure_ready, run_sandboxed, sandboxed_verify

TIMEOUT_S = 5.0


@pytest.fixture
def removed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run the snippet in a local Python instead of a container, and record container removals."""
    names: list[str] = []
    monkeypatch.setattr(sandbox, "_command", lambda name: [sys.executable, "-I", "-"])
    monkeypatch.setattr(sandbox, "_remove_container", names.append)
    return names


def test_the_container_has_no_network_no_writable_disk_and_no_privileges() -> None:
    command = sandbox._command("c1")

    assert command[:3] == ["docker", "run", "--rm"]
    for flag in (
        "--runtime=runsc",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=256m",
        "--memory-swap=256m",
        "--pids-limit=64",
    ):
        assert flag in command
    assert command[command.index("--user") + 1] == "65534:65534"
    assert command[-3:] == ["python", "-I", "-"]
    # Nothing from the host is mounted or shared.
    assert not {"-v", "--volume", "--mount", "--privileged", "--network=host"} & set(command)


def test_the_snippet_goes_in_on_stdin_and_its_output_comes_back(removed: list[str]) -> None:
    run = run_sandboxed("print(6 * 7)", TIMEOUT_S)

    assert (run.returncode, run.stdout.strip(), run.timed_out) == (0, "42", False)
    assert removed == []


def test_a_crash_is_reported_with_its_stderr(removed: list[str]) -> None:
    run = run_sandboxed("raise ValueError('boom')", TIMEOUT_S)

    assert run.returncode == 1 and "boom" in run.stderr


def test_a_runaway_snippet_is_stopped_and_its_container_removed(
    removed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "STARTUP_ALLOWANCE_S", 0.0)  # no container starts here

    run = run_sandboxed("while True: pass", 0.5)

    assert run.timed_out
    assert len(removed) == 1 and removed[0].startswith("arena-snippet-")


def test_a_snippet_that_floods_stdout_is_stopped(removed: list[str]) -> None:
    run = run_sandboxed("while True: print('x' * 1000)", TIMEOUT_S)

    assert run.returncode != 0 and not run.timed_out
    assert str(MAX_OUTPUT_BYTES) in run.stderr
    assert len(removed) == 1


def test_a_docker_failure_is_not_blamed_on_the_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail = "import sys; sys.stderr.write('docker: daemon not running'); sys.exit(125)"
    monkeypatch.setattr(sandbox, "_command", lambda name: [sys.executable, "-I", "-c", fail])

    with pytest.raises(ConfigError, match="daemon not running"):
        run_sandboxed("print(1)", TIMEOUT_S)


def test_sandboxed_verify_judges_like_the_local_verifier(removed: list[str]) -> None:
    assert sandboxed_verify("42", "print(2 * 21)", TIMEOUT_S).passed
    assert sandboxed_verify("1/2", "print(0.5)", TIMEOUT_S).passed
    wrong = sandboxed_verify("42", "print(41)", TIMEOUT_S)
    assert not wrong.passed and "mismatch" in wrong.reason
    crashed = sandboxed_verify("42", "raise ValueError('boom')", TIMEOUT_S)
    assert not crashed.passed and "boom" in crashed.reason


class FakeDocker:
    """Stands in for `subprocess.run` so the readiness check needs no Docker."""

    def __init__(self, runtimes: dict[str, Any], image_present: bool = True) -> None:
        self.runtimes = runtimes
        self.image_present = image_present
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[1] == "info":
            return subprocess.CompletedProcess(command, 0, json.dumps(self.runtimes), "")
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0 if self.image_present else 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_ready_when_docker_has_gvisor_and_the_image(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker({"runc": {}, "runsc": {}})
    monkeypatch.setattr(subprocess, "run", fake)

    ensure_ready()

    assert all(call[1] != "pull" for call in fake.calls)


def test_the_image_is_pulled_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker({"runsc": {}}, image_present=False)
    monkeypatch.setattr(subprocess, "run", fake)

    ensure_ready()

    assert ["docker", "pull", sandbox.IMAGE] in fake.calls


def test_no_gvisor_means_no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", FakeDocker({"runc": {}}))

    with pytest.raises(ConfigError, match="runsc"):
        ensure_ready()


def test_no_docker_means_no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(command: list[str], **_: Any) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(ConfigError, match="docker"):
        ensure_ready()


@pytest.fixture
def gvisor() -> None:
    """The real thing: skips unless this machine's Docker has gVisor (see D-044)."""
    try:
        ensure_ready()
    except ConfigError as exc:
        pytest.skip(f"no gVisor sandbox here ({exc})")


def test_gvisor_runs_a_snippet(gvisor: None) -> None:
    assert sandboxed_verify("42", "print(6 * 7)", 20.0).passed


def test_gvisor_blocks_the_network(gvisor: None) -> None:
    code = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"
    run = run_sandboxed(code, 20.0)
    assert run.returncode != 0 and not run.timed_out


def test_gvisor_has_no_writable_disk_and_no_host_files(gvisor: None, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("x")
    code = (
        "import os\n"
        f"print(os.path.exists({str(tmp_path / 'secret.txt')!r}))\n"
        "try:\n    open('/etc/pwned', 'w')\nexcept OSError:\n    print('read-only')\n"
    )
    run = run_sandboxed(code, 20.0)
    assert run.stdout.split() == ["False", "read-only"]


def test_gvisor_contains_a_fork_bomb_and_a_memory_hog(gvisor: None) -> None:
    fork = "import os\nwhile True:\n    os.fork()\n"
    hog = "x = bytearray(2 * 1024**3)\nprint('allocated')"
    assert "allocated" not in run_sandboxed(hog, 20.0).stdout
    run = run_sandboxed(fork, 10.0)
    assert run.timed_out or run.returncode != 0
