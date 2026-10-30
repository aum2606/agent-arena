import argparse
import logging
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from arena.battle_log import BattleLog
from arena.config import ConfigError, load_config
from arena.llm import LlmClient, LlmError
from arena.models import MatchRecord
from arena.orchestrator import run_match
from arena.stats import ResultsError, append_record, compute_stats, format_stats, load_records

DEFAULT_CONFIG = Path("config/fighters.toml")
RUNS_DIR = Path("runs")


def _result_text(record: MatchRecord) -> str:
    winner = record.result.winner
    if winner is None:
        return f"draw by {record.result.reason}"
    name = record.fighter_a if winner == "a" else record.fighter_b
    return f"{name} wins by {record.result.reason}"


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
    lines.append(f"Result: {_result_text(record)}")
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


def _sim(args: argparse.Namespace) -> None:
    if args.n < 1:
        raise ConfigError("--n must be at least 1")
    config = load_config(args.config)
    names = list(config.fighters)
    if len(names) < 2:
        raise ConfigError(f"sim needs at least 2 fighters in {args.config}, found {len(names)}")

    records = load_records(args.out)
    client = LlmClient(config.providers, config.settings)
    # Seeding by match index keeps the pairing identical when a sim is resumed.
    for i in range(len(records), args.n):
        a, b = random.Random(i).sample(names, 2)
        match_id = f"sim_{i:04d}"
        log = BattleLog(match_id)
        record = run_match(
            config.fighters[a], config.fighters[b], client.complete, config.settings, log
        )
        log.write(RUNS_DIR / "logs" / f"{match_id}.json")
        append_record(args.out, record)
        records.append(record)
        print(f"[{i + 1}/{args.n}] {a} vs {b}: {_result_text(record)}")
    print(format_stats(compute_stats(records)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arena")
    commands = parser.add_subparsers(dest="command", required=True)
    match = commands.add_parser("match", help="run one match between two fighters")
    match.add_argument("--a", required=True, help="fighter name (attacks first)")
    match.add_argument("--b", required=True, help="fighter name")
    match.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    match.set_defaults(run=_match)
    sim = commands.add_parser("sim", help="run many matches and print balance stats")
    sim.add_argument("--n", type=int, required=True, help="total matches wanted, incl. saved ones")
    sim.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sim.add_argument("--out", type=Path, default=RUNS_DIR / "sim.jsonl", help="results file")
    sim.set_defaults(run=_sim)
    args = parser.parse_args(argv)

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("arena").setLevel(logging.INFO)
    try:
        args.run(args)
    except (ConfigError, LlmError, ResultsError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
