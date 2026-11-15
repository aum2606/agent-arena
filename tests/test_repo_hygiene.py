"""The repository's setup: ignore files, pins, CI and dependency settings (D-071)."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def ignored(path: str) -> bool:
    return (
        subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, check=False).returncode == 0
    )


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", "web/.env.local", ".env.production", "tls/server.pem", "deploy/id.key"],
)
def test_secret_files_are_git_ignored(path: str) -> None:
    assert ignored(path)


def test_the_example_env_file_is_not_ignored() -> None:
    assert not ignored(".env.example")


@pytest.mark.parametrize("pattern", [".env", ".env.*", "*.pem", "*.key"])
def test_secret_files_stay_out_of_the_docker_build_context(pattern: str) -> None:
    assert pattern in text(".dockerignore").splitlines()


def test_every_base_image_is_pinned_by_digest() -> None:
    images = []
    for dockerfile in ("api.Dockerfile", "web.Dockerfile", "sandbox.Dockerfile"):
        for line in text(f"docker/{dockerfile}").splitlines():
            match = re.match(r"(?:FROM|COPY --from=)\s*(?:--\S+\s+)?(\S+)", line)
            if (
                match
                and "AS" not in match.group(1)
                and not match.group(1).startswith(("build", "/"))
            ):
                images.append(match.group(1))
    compose = yaml.safe_load(text("docker-compose.yml"))["services"]
    images += [s["image"] for s in compose.values() if "image" in s]

    assert len(images) >= 6, images
    assert [i for i in images if "@sha256:" not in i] == []


def test_every_github_action_is_pinned_to_a_commit() -> None:
    uses = re.findall(r"uses:\s*(\S+)", text(".github/workflows/ci.yml"))

    assert uses and [u for u in uses if not re.search(r"@[0-9a-f]{40}$", u)] == []


def test_ci_installs_from_the_lock_audits_and_builds_the_images() -> None:
    ci = text(".github/workflows/ci.yml")

    assert "uv sync --locked" in ci and "--frozen" not in ci  # a stale lock fails CI
    assert "npm audit --audit-level=high" in ci
    assert ci.count("docker build") >= 2  # the API and web images once broke unnoticed (D-068)


def test_dependabot_watches_every_kind_of_dependency() -> None:
    config = yaml.safe_load(text(".github/dependabot.yml"))

    assert {u["package-ecosystem"] for u in config["updates"]} == {
        "uv",
        "npm",
        "github-actions",
        "docker",
    }


def test_modules_imported_directly_are_declared() -> None:
    declared = " ".join(tomllib.loads(text("pyproject.toml"))["project"]["dependencies"])

    assert "httpx2" in declared  # src/arena/llm.py imports it; it only arrived through openai


@pytest.mark.skipif(
    sys.platform == "win32", reason="the memory limit is set with resource, a POSIX module"
)
def test_the_answer_checker_limits_its_own_memory() -> None:
    code = (
        "import resource; from arena import equality; equality._limit_memory(); "
        "print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    from arena import equality

    assert int(out.stdout) == equality.MEMORY_LIMIT_BYTES


def test_the_answer_checker_does_not_put_the_working_directory_on_its_path() -> None:
    from arena import equality

    assert "-P" in equality.HELPER_COMMAND


def test_shell_scripts_keep_unix_line_endings_even_on_a_windows_checkout() -> None:
    done = subprocess.run(
        ["git", "check-attr", "eol", "deploy/run-worker.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip().endswith("eol: lf")
