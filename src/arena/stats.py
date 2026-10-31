import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from arena.models import MatchRecord, MatchResult, Outcome, TurnResult

GATE_MAX_ROLE_WIN_RATE = 0.70
GATE_MIN_MATCHES = 100


class ResultsError(Exception):
    pass


@dataclass(frozen=True)
class Stats:
    matches: int
    turns: int
    hits: int
    blocks: int
    backfires: int
    total_damage: float
    kos: int
    decisions: int
    draws: int

    @property
    def attacker_win_rate(self) -> float:
        return self.hits / self.turns

    @property
    def defender_win_rate(self) -> float:
        return (self.blocks + self.backfires) / self.turns

    @property
    def backfire_rate(self) -> float:
        return self.backfires / self.turns

    @property
    def average_damage_per_turn(self) -> float:
        return self.total_damage / self.turns

    @property
    def average_match_length(self) -> float:
        return self.turns / self.matches


def compute_stats(records: list[MatchRecord]) -> Stats:
    """Needs at least one record; every match has at least one turn."""
    turns = [t for r in records for t in r.turns]
    outcomes = Counter(t.outcome for t in turns)
    endings = Counter(
        "ko" if r.result.reason == "ko" else "draw" if r.result.winner is None else "decision"
        for r in records
    )
    return Stats(
        matches=len(records),
        turns=len(turns),
        hits=outcomes["hit"],
        blocks=outcomes["block"],
        backfires=outcomes["backfire"],
        total_damage=sum(t.damage for t in turns),
        kos=endings["ko"],
        decisions=endings["decision"],
        draws=endings["draw"],
    )


def _gate(stats: Stats) -> str:
    if stats.matches < GATE_MIN_MATCHES:
        return f"INCOMPLETE ({stats.matches}/{GATE_MIN_MATCHES} matches)"
    dominant, rate = max(
        [("attacker", stats.attacker_win_rate), ("defender", stats.defender_win_rate)],
        key=lambda role: role[1],
    )
    if rate <= GATE_MAX_ROLE_WIN_RATE:
        return "PASS"
    return f"FAIL ({dominant} wins {rate:.1%} of turns)"


def format_stats(stats: Stats) -> str:
    return "\n".join(
        [
            f"Matches: {stats.matches}, turns: {stats.turns}",
            f"Attacker wins {stats.attacker_win_rate:.1%} of turns (hit {stats.hits})",
            f"Defender wins {stats.defender_win_rate:.1%} of turns "
            f"(block {stats.blocks}, backfire {stats.backfires})",
            f"Backfire rate: {stats.backfire_rate:.1%}",
            f"Average damage per turn: {stats.average_damage_per_turn:.1f}",
            f"Average match length: {stats.average_match_length:.1f} turns",
            f"Endings: KO {stats.kos}, decision {stats.decisions}, draw {stats.draws}",
            f"Gate: {_gate(stats)} (neither role above "
            f"{GATE_MAX_ROLE_WIN_RATE:.0%} of turns over {GATE_MIN_MATCHES}+ matches)",
        ]
    )


def append_record(path: Path, record: MatchRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def load_records(path: Path) -> list[MatchRecord]:
    """Missing file means no matches yet. A damaged line (e.g. a crash mid-write) is an error."""
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            raw = json.loads(line)
            records.append(
                MatchRecord(
                    raw["fighter_a"],
                    raw["fighter_b"],
                    [TurnResult(**t) for t in raw["turns"]],
                    raw["hp_a"],
                    raw["hp_b"],
                    MatchResult(**raw["result"]),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ResultsError(f"{path}:{number}: unreadable result line ({exc!r})") from exc
    return records


def attack_outcomes(records: list[MatchRecord], name: str) -> list[Outcome]:
    """Outcomes of the fighter's own attacks across the matches, oldest first."""
    outcomes: list[Outcome] = []
    for record in records:
        side = "a" if record.fighter_a == name else "b" if record.fighter_b == name else None
        if side is not None:
            outcomes += [t.outcome for t in record.turns if t.attacker == side]
    return outcomes
