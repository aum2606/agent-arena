import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from arena.battle_log import BattleLog
from arena.config import ConfigError, load_config
from arena.llm import LlmClient, LlmError
from arena.models import MatchRecord
from arena.orchestrator import run_match

DEFAULT_CONFIG = Path("config/fighters.toml")
RUNS_DIR = Path("runs")


def format_summary(record: MatchRecord) -> str:
    names = {"a": record.fighter_a, "b": record.fighter_b}
    lines = [f"{record.fighter_a} (A) vs {record.fighter_b} (B)"]
    lines += [
        f"Turn {t.turn}: {names[t.attacker]} attacks -> {t.outcome}, "
        f"{names[t.target]} takes {t.damage:g} damage"
        for t in record.turns
    ]
    lines.append(
        f"Final HP: {record.fighter_a} {record.hp_a:g}, {record.fighter_b} {record.hp_b:g}"
    )
    winner = record.result.winner
    if winner is None:
        lines.append(f"Result: draw by {record.result.reason}")
    else:
        lines.append(f"Result: {names[winner]} wins by {record.result.reason}")
    return "\n".join(lines)


def _match(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    for name in (args.a, args.b):
        if name not in config.fighters:
            available = ", ".join(config.fighters) or "none"
            raise ConfigError(f"unknown fighter {name!r} (available: {available})")

    match_id = datetime.now(UTC).strftime("m_%Y%m%dT%H%M%S")
    log = BattleLog(match_id)
    client = LlmClient(config.providers, config.settings)
    record = run_match(
        config.fighters[args.a], config.fighters[args.b], client.complete, config.settings, log
    )
    path = RUNS_DIR / f"{match_id}.json"
    log.write(path)
    print(format_summary(record))
    print(f"Log: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arena")
    commands = parser.add_subparsers(dest="command", required=True)
    match = commands.add_parser("match", help="run one match between two fighters")
    match.add_argument("--a", required=True, help="fighter name (attacks first)")
    match.add_argument("--b", required=True, help="fighter name")
    match.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    match.set_defaults(run=_match)
    args = parser.parse_args(argv)

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("arena").setLevel(logging.INFO)
    try:
        args.run(args)
    except (ConfigError, LlmError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
