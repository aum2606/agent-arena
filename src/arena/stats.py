import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from arena.models import MatchRecord, MatchResult, Outcome, TurnResult

GATE_MAX_ROLE_WIN_RATE = 0.70
GATE_MIN_MATCHES = 100


class ResultsError(Exception):
    pass


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a rate; wide when n is small, (0, 1) when there is no data."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(centre - margin, 0.0), min(centre + margin, 1.0)


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
    def attacker_interval(self) -> tuple[float, float]:
        return wilson_interval(self.hits, self.turns)

    @property
    def defender_interval(self) -> tuple[float, float]:
        low, high = self.attacker_interval  # the defender wins every turn the attacker does not
        return 1 - high, 1 - low

    @property
    def verified_hit_rate(self) -> float | None:
        """Hits among attacks that reached a defender (backfires are not counted)."""
        reached = self.hits + self.blocks
        return self.hits / reached if reached else None

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
    dominant, rate, (low, high) = max(
        [
            ("attacker", stats.attacker_win_rate, stats.attacker_interval),
            ("defender", stats.defender_win_rate, stats.defender_interval),
        ],
        key=lambda role: role[1],
    )
    # Judged on the interval, not the point estimate, so a run near 70% is not called either way.
    over, under = low > GATE_MAX_ROLE_WIN_RATE, high <= GATE_MAX_ROLE_WIN_RATE
    interval = f"95% interval {low:.0%}-{high:.0%}"
    if stats.matches < GATE_MIN_MATCHES:
        text = f"INCOMPLETE ({stats.matches}/{GATE_MIN_MATCHES} matches)"
        if over:
            text += f"; cannot pass: {dominant} wins at least {low:.0%} of turns"
        return text
    if under:
        return "PASS"
    if over:
        return f"FAIL ({dominant} wins {rate:.1%} of turns, {interval})"
    return f"INCONCLUSIVE ({dominant} wins {rate:.1%} of turns, {interval})"


def _reached_lines(stats: Stats) -> list[str]:
    rate = stats.verified_hit_rate
    a_low, a_high = stats.attacker_interval
    d_low, d_high = stats.defender_interval
    lines = [f"95% intervals: attacker {a_low:.1%}-{a_high:.1%}, defender {d_low:.1%}-{d_high:.1%}"]
    if rate is not None:
        reached = stats.hits + stats.blocks
        lines.insert(0, f"Attacks that reached a defender: {reached}, hit rate {rate:.1%}")
    return lines


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
            *_reached_lines(stats),
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
