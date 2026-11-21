from pathlib import Path

import yaml
from helpers import load_compose

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


PROD = Path(__file__).parents[1] / "docker-compose.prod.yml"


def prod() -> dict[str, dict[str, object]]:
    return load_compose(PROD)["services"]  # type: ignore[no-any-return]


def env_of(service: str) -> dict[str, str]:
    env = prod()[service]["environment"]
    assert isinstance(env, dict)
    return env


def test_the_public_override_refuses_to_start_without_its_secrets() -> None:
    # `${NAME:?message}` makes compose stop, not start on a blank or local default (D-072).
    required = {
        "api": [
            "DATABASE_URL",
            "REDIS_URL",
            "KEY_PUBLIC_KEY",
            "PUBLIC_URL",
            "CLIENT_IP_HEADER",
        ],
        "web": ["CLIENT_IP_HEADER"],
        "postgres": ["POSTGRES_PASSWORD"],
    }
    for service, names in required.items():
        for name in names:
            assert ":?" in env_of(service)[name], f"{service} {name} may start blank"
    redis_command = " ".join(str(part) for part in prod()["redis"]["command"])  # type: ignore[attr-defined]
    assert "--requirepass" in redis_command and "${REDIS_PASSWORD:?" in redis_command


def test_the_public_override_turns_the_local_conveniences_off() -> None:
    assert env_of("api")["ARENA_DEV_LOGIN"] == "0"
    # The container worker has no sandbox: a public deployment runs the worker on the host instead.
    assert prod()["worker"]["profiles"]  # type: ignore[attr-defined]


def test_the_public_override_keeps_everything_on_the_loopback_address() -> None:
    merged = {**services(), **prod()}
    for name, service in merged.items():
        for port in service.get("ports", []):  # type: ignore[attr-defined]
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} to the network"


def test_the_public_override_restarts_what_it_runs() -> None:
    for name in ("postgres", "redis", "api", "web"):
        assert prod()[name]["restart"] == "unless-stopped"


def test_every_setting_the_public_override_requires_is_in_the_example_env_file() -> None:
    import re

    required = set(re.findall(r"\$\{(\w+):\?", PROD.read_text(encoding="utf-8")))
    example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    listed = set(re.findall(r"^(\w+)=", example, flags=re.MULTILINE))

    assert required <= listed, f"missing from .env.example: {sorted(required - listed)}"


def test_the_public_apis_environment_holds_nothing_that_opens_a_stored_key() -> None:
    # D-082: it seals keys to the public key. The base file's local secret is reset away, and the
    # private key is only ever given to the worker on the host.
    for service in ("api", "web", "migrate", "postgres", "redis"):
        env = prod()[service].get("environment", {})
        assert isinstance(env, dict)
        assert "KEY_PRIVATE_KEY" not in env and "KEY_OLD_PRIVATE_KEYS" not in env
    api = env_of("api")
    assert "KEY_ENCRYPTION_SECRET" in api and api["KEY_ENCRYPTION_SECRET"] is None
    assert "KEY_ENCRYPTION_OLD_SECRETS" not in api
