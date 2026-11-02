"""Load battle logs into the database: `python -m arena_api.import_logs FOLDER [--prefix P]`."""

import argparse
import json
import sys
from pathlib import Path

from arena.config import ConfigError
from arena_api import store
from arena_api.db import migrate
from arena_api.replays import VALID_ID, ReplayError, parse_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arena_api.import_logs")
    parser.add_argument("folder", type=Path, help="folder of battle-log .json files")
    parser.add_argument(
        "--prefix", default="", help="put in front of each file name to make the id"
    )
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        print(f"error: {args.folder} is not a folder", file=sys.stderr)
        return 1

    try:
        migrate()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    imported = existing = 0
    skipped: list[str] = []
    for path in sorted(args.folder.glob("*.json")):
        match_id = f"{args.prefix}{path.stem}"
        try:
            if not VALID_ID.fullmatch(match_id):
                raise ReplayError(f"{match_id!r} is not a valid id")
            log = json.loads(path.read_text(encoding="utf-8"))
            summary = parse_replay(match_id, log).summary
        except (OSError, ValueError, ReplayError) as exc:
            skipped.append(f"{path.name}: {exc}")
            continue
        if store.insert_finished(match_id, log, summary):
            imported += 1
        else:
            existing += 1
    print(f"imported {imported}, already there {existing}, skipped {len(skipped)}")
    for line in skipped:
        print(f"  skipped {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
