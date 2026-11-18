"""The worker script a self-hoster runs next to Docker and gVisor (D-072)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "deploy" / "run-worker.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="a POSIX shell script"
)

GOOD_ENV = {
    "POSTGRES_PASSWORD": "pgpass",
    "REDIS_PASSWORD": "redispass",
    "KEY_ENCRYPTION_SECRET": "secret",
    "PUBLIC_URL": "https://arena.example.org",
}


def stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def run(tmp_path: Path, env_file: dict[str, str], runtimes: str = '{"runc":{},"runsc":{}}'):
    (tmp_path / "bin").mkdir(exist_ok=True)
    stub(tmp_path / "bin", "docker", f"echo '{runtimes}'")
    stub(
        tmp_path / "bin",
        "uv",
        'echo "uv $*"; echo "DB=$DATABASE_URL"; echo "REDIS=$REDIS_URL"; '
        'echo "GITHUB=${GITHUB_CLIENT_SECRET:-none}"; echo "GROQ=${GROQ_API_KEY:-none}"',
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("".join(f"{k}={v}\n" for k, v in env_file.items()), encoding="utf-8")
    path = f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"
    clean = {"PATH": path, "ENV_FILE": str(env_path)}
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=clean, check=False, cwd=tmp_path
    )


def test_it_starts_the_worker_with_urls_built_from_the_passwords(tmp_path: Path) -> None:
    done = run(tmp_path, GOOD_ENV)

    assert done.returncode == 0, done.stderr
    assert "uv run --no-dev arq arena_api.jobs.WorkerSettings" in done.stdout
    assert "DB=postgresql://arena:pgpass@127.0.0.1:5442/arena" in done.stdout
    assert "REDIS=redis://:redispass@127.0.0.1:6379" in done.stdout


@pytest.mark.parametrize("missing", sorted(GOOD_ENV))
def test_it_refuses_to_start_without_a_required_setting(tmp_path: Path, missing: str) -> None:
    done = run(tmp_path, {k: v for k, v in GOOD_ENV.items() if k != missing})

    assert done.returncode != 0
    assert missing in done.stderr


def test_it_refuses_a_plain_http_public_address(tmp_path: Path) -> None:
    done = run(tmp_path, {**GOOD_ENV, "PUBLIC_URL": "http://arena.example.org"})

    assert done.returncode != 0
    assert "https" in done.stderr


def test_it_never_runs_unsandboxed(tmp_path: Path) -> None:
    done = run(tmp_path, {**GOOD_ENV, "ARENA_SANDBOX": "off"})

    assert done.returncode != 0
    assert "ARENA_SANDBOX" in done.stderr


def test_it_refuses_a_docker_without_gvisor(tmp_path: Path) -> None:
    done = run(tmp_path, GOOD_ENV, runtimes='{"runc":{}}')

    assert done.returncode != 0
    assert "runsc" in done.stderr


def test_it_refuses_an_env_file_with_windows_line_endings(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    done = run(tmp_path, {k: v + "\r" for k, v in GOOD_ENV.items()})

    assert done.returncode != 0
    assert "line endings" in done.stderr


def test_the_worker_gets_only_the_settings_it_needs(tmp_path: Path) -> None:
    extra = {"GITHUB_CLIENT_SECRET": "ghs_secret", "GROQ_API_KEY": "gsk_provider_key"}

    done = run(tmp_path, GOOD_ENV | extra)

    assert done.returncode == 0, done.stderr
    assert "GITHUB=none" in done.stdout  # model-written code must never be near it (D-068)
    assert "GROQ=gsk_provider_key" in done.stdout  # the worker does need the provider keys
