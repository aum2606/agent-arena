from pathlib import Path

import yaml

COMPOSE = Path(__file__).parents[1] / "docker-compose.yml"


def test_the_compose_worker_starts_without_gvisor_in_its_container() -> None:
    # Its container has no Docker, so the default sandbox check (D-044) would stop it at start-up.
    worker = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["worker"]

    assert worker["environment"]["ARENA_SANDBOX"] == "${ARENA_SANDBOX:-off}"
    assert worker["environment"]["DATABASE_URL"]  # still gets the shared settings
