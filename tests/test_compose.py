from pathlib import Path

import yaml

COMPOSE = Path(__file__).parents[1] / "docker-compose.yml"


def test_the_compose_worker_starts_without_gvisor_in_its_container() -> None:
    # Its container has no Docker, so the default sandbox check (D-044) would stop it at start-up.
    worker = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["worker"]

    assert worker["environment"]["ARENA_SANDBOX"] == "${ARENA_SANDBOX:-off}"
    assert worker["environment"]["DATABASE_URL"]  # still gets the shared settings


def services() -> dict[str, dict[str, object]]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]  # type: ignore[no-any-return]


def test_the_worker_gets_only_the_settings_it_needs_not_the_whole_env_file() -> None:
    worker = services()["worker"]
    env = worker["environment"]
    assert isinstance(env, dict)

    assert "env_file" not in worker  # the GitHub client secret must not reach model-written code
    assert not any(name.startswith("GITHUB_") for name in env)
    for needed in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "PUBLIC_URL"):
        assert needed in env


def test_the_public_address_can_be_set_for_the_api_and_the_worker() -> None:
    for name in ("api", "worker"):
        env = services()[name]["environment"]
        assert isinstance(env, dict)
        assert env["PUBLIC_URL"] == "${PUBLIC_URL:-http://127.0.0.1:3100}"


def test_the_api_image_copies_every_file_the_package_metadata_names() -> None:
    # `uv sync` builds the project and fails if its readme or licence file is missing; once it did.
    import tomllib

    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    needed = [project["readme"], *project.get("license-files", [])]
    copied = " ".join(
        line
        for line in (root / "docker" / "api.Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY")
    )

    for name in needed:
        assert name in copied, f"docker/api.Dockerfile does not COPY {name}"
