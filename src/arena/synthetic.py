"""Scripted fighters for balance experiments that need no LLM calls (D-020).

Every fighter has a skill in [0, 1]. A problem has a difficulty in [0, 1]. Succeeding at
anything (deriving an attack's answer, solving a problem) is a coin flip weighted by a logistic
curve of skill minus difficulty. Matches run through the real `run_match`, so only the players
are fake: the rules, damage and stats are the production code.
"""

import math
import random
import re
from dataclasses import dataclass

from arena.battle_log import BattleLog
from arena.config import Settings
from arena.llm import Completion
from arena.models import Fighter, MatchRecord
from arena.orchestrator import run_match
from arena.prompts import ATTACK_REQUEST
from arena.stats import GATE_MAX_ROLE_WIN_RATE, compute_stats
from arena.verifier import Verification, answers_match

SLOPE = 10.0  # how sharply success flips around skill == difficulty
DIFFICULTY_SPREAD = 0.1  # std dev of the difficulty a fighter draws for each problem it poses
SKILLS = (0.3, 0.5, 0.7, 0.9)
ADVANTAGES = (0.0, 0.1, 0.2, 0.3)
DIFFICULTIES = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# Only `snippet_timeout_s` is read by the orchestrator and `synthetic_verify` ignores it.
_SETTINGS = Settings(
    turn_time_limit_s=0.0,
    turn_max_tokens=0,
    snippet_timeout_s=0.0,
    call_delay_s=0.0,
    max_retries=0,
    backoff_base_s=0.0,
)
_DIFFICULTY_IN_PROBLEM = re.compile(r"d=(\d+\.\d+)")
_QUALITY_IN_PROBLEM = re.compile(r"q=([01])")
_SNIPPET = re.compile(r"print\((\d+)\)")


@dataclass(frozen=True)
class Skill:
    level: float
    attack_bonus: float  # extra reliability when deriving an attack's answer (the snippet's help)


def success_probability(skill: float, difficulty: float) -> float:
    return 1.0 / (1.0 + math.exp(-SLOPE * (skill - difficulty)))


class SyntheticLlm:
    """Plays the `complete` callable: replies to attack and defense prompts from skill alone.

    A problem is well posed (`q=1`) when its attacker derived the answer correctly. With
    `answer_from_snippet` the attacker's stated answer is whatever its snippet prints, so a
    badly derived problem still verifies but cannot be answered: it is a broken problem.
    """

    def __init__(
        self,
        skills: dict[str, Skill],
        difficulty: float,
        rng: random.Random,
        answer_from_snippet: bool = False,
    ) -> None:
        self._skills = skills
        self._difficulty = difficulty
        self._rng = rng
        self._answer_from_snippet = answer_from_snippet
        self._problems = 0
        self.fair_hits = 0  # failed defenses of well-posed problems

    def complete(self, fighter: Fighter, system: str, user: str) -> Completion:
        skill = self._skills[fighter.name]
        if user.endswith(ATTACK_REQUEST):
            d = min(1.0, max(0.0, self._rng.gauss(self._difficulty, DIFFICULTY_SPREAD)))
            derived = self._rng.random() < success_probability(skill.level + skill.attack_bonus, d)
            self._problems += 1
            problem = f"Synthetic problem #{self._problems} d={d:.3f} q={int(derived)}"
            if derived:
                number, stated = 1, "1"
            elif self._answer_from_snippet:
                number, stated = 3, "3"  # snippet and answer agree, but not on this problem
            else:
                number, stated = 1, "2"  # the stated answer disagrees with the snippet
            return Completion(
                f"<problem>{problem}</problem><code>print({number})</code>"
                f"<answer>{stated}</answer>",
                False,
            )
        difficulty = _tagged_number(_DIFFICULTY_IN_PROBLEM, user)
        solved = self._rng.random() < success_probability(skill.level, difficulty)
        if _tagged_number(_QUALITY_IN_PROBLEM, user) == 1.0 and not solved:
            self.fair_hits += 1
        return Completion(f"<answer>{'1' if solved else '2'}</answer>", False)


def _tagged_number(pattern: re.Pattern[str], text: str) -> float:
    found = pattern.search(text)
    if found is None:
        raise ValueError("defense prompt carries no synthetic problem tags")
    return float(found.group(1))


def synthetic_verify(stated_answer: str, snippet: str, _timeout_s: float) -> Verification:
    """Stand-in for `verify_attack`: the scripted snippet is `print(N)`, so no subprocess."""
    printed = _SNIPPET.fullmatch(snippet.strip())
    if printed is None:
        return Verification(False, "unsupported synthetic snippet")
    if not answers_match(printed.group(1), stated_answer):
        return Verification(False, f"mismatch: snippet printed {printed.group(1)!r}")
    return Verification(True, "ok")


@dataclass(frozen=True)
class SyntheticRun:
    records: list[MatchRecord]
    fair_hits: int  # hits that came from failed defenses of well-posed problems


def play_synthetic(
    skills: tuple[Skill, Skill],
    difficulty: float,
    matches: int,
    seed: int,
    answer_from_snippet: bool = False,
) -> SyntheticRun:
    rng = random.Random(seed)
    a = Fighter("synthetic-a", "synthetic", "synthetic", "")
    b = Fighter("synthetic-b", "synthetic", "synthetic", "")
    llm = SyntheticLlm({a.name: skills[0], b.name: skills[1]}, difficulty, rng, answer_from_snippet)
    records = [
        run_match(a, b, llm.complete, _SETTINGS, BattleLog(f"synthetic_{i}"), rng, synthetic_verify)
        for i in range(matches)
    ]
    return SyntheticRun(records, llm.fair_hits)


def sweep(matches: int, difficulty: float, seed: int) -> dict[tuple[float, float], float]:
    """Attacker win rate per turn when both fighters share a skill and an attack bonus."""
    rates = {}
    for level in SKILLS:
        for bonus in ADVANTAGES:
            skill = Skill(level, bonus)
            run = play_synthetic((skill, skill), difficulty, matches, seed)
            rates[(level, bonus)] = compute_stats(run.records).attacker_win_rate
    return rates


def _gate_mark(attacker_rate: float) -> str:
    return "*" if max(attacker_rate, 1.0 - attacker_rate) <= GATE_MAX_ROLE_WIN_RATE else ""


def format_sweep(rates: dict[tuple[float, float], float]) -> str:
    width = len("bonus +0.0") + 2
    lines = [
        f"Attacker win rate per turn (* = gate passes: neither role above "
        f"{GATE_MAX_ROLE_WIN_RATE:.0%})",
        "skill  " + "".join(f"bonus +{bonus:.1f}".ljust(width) for bonus in ADVANTAGES),
    ]
    for level in SKILLS:
        cells = []
        for bonus in ADVANTAGES:
            rate = rates[(level, bonus)]
            cells.append(f"{rate:.0%}{_gate_mark(rate)}".ljust(width))
        lines.append(f"{level:<7.1f}" + "".join(cells))
    return "\n".join(lines)


@dataclass(frozen=True)
class RuleRow:
    difficulty: float
    now: float  # attacker win rate when a stated answer that differs from the snippet backfires
    backfire: float  # backfire rate under that rule
    snippet: float  # attacker win rate when the snippet's output is the answer
    fair: float  # share of turns hit through a solvable problem under that rule


def compare_rules(skill: float, bonus: float, matches: int, seed: int) -> list[RuleRow]:
    """Both fighters share `skill` and `bonus`; problem difficulty goes through DIFFICULTIES."""
    pair = (Skill(skill, bonus), Skill(skill, bonus))
    rows = []
    for difficulty in DIFFICULTIES:
        now = compute_stats(play_synthetic(pair, difficulty, matches, seed).records)
        new = play_synthetic(pair, difficulty, matches, seed, answer_from_snippet=True)
        new_stats = compute_stats(new.records)
        rows.append(
            RuleRow(
                difficulty,
                now.attacker_win_rate,
                now.backfire_rate,
                new_stats.attacker_win_rate,
                new.fair_hits / new_stats.turns,
            )
        )
    return rows


def format_comparison(rows: list[RuleRow], skill: float, bonus: float) -> str:
    lines = [
        f"Rule comparison at skill {skill}, attacker bonus {bonus} "
        "(attacker win rate per turn, * = gate passes)",
        "difficulty  now: win  backfire    snippet answer: win  from solvable problems",
    ]
    for row in rows:
        now = f"{row.now:.0%}{_gate_mark(row.now)}"
        snippet = f"{row.snippet:.0%}{_gate_mark(row.snippet)}"
        lines.append(
            f"{row.difficulty:<12.1f}{now:<10}{row.backfire:<12.0%}{snippet:<21}{row.fair:.0%}"
        )
    return "\n".join(lines)
