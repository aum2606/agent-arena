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
_SNIPPET = re.compile(r"print\((\d+)\)")


@dataclass(frozen=True)
class Skill:
    level: float
    attack_bonus: float  # extra reliability when deriving an attack's answer (the snippet's help)


def success_probability(skill: float, difficulty: float) -> float:
    return 1.0 / (1.0 + math.exp(-SLOPE * (skill - difficulty)))


class SyntheticLlm:
    """Plays the `complete` callable: replies to attack and defense prompts from skill alone."""

    def __init__(self, skills: dict[str, Skill], difficulty: float, rng: random.Random) -> None:
        self._skills = skills
        self._difficulty = difficulty
        self._rng = rng
        self._problems = 0

    def complete(self, fighter: Fighter, system: str, user: str) -> Completion:
        skill = self._skills[fighter.name]
        if user.endswith(ATTACK_REQUEST):
            d = min(1.0, max(0.0, self._rng.gauss(self._difficulty, DIFFICULTY_SPREAD)))
            derived = self._rng.random() < success_probability(skill.level + skill.attack_bonus, d)
            self._problems += 1
            problem = f"Synthetic problem #{self._problems} d={d:.3f}"
            stated = "1" if derived else "2"  # the snippet always prints 1
            return Completion(
                f"<problem>{problem}</problem><code>print(1)</code><answer>{stated}</answer>",
                False,
            )
        found = _DIFFICULTY_IN_PROBLEM.search(user)
        if found is None:
            raise ValueError("defense prompt carries no synthetic difficulty")
        solved = self._rng.random() < success_probability(skill.level, float(found.group(1)))
        return Completion(f"<answer>{'1' if solved else '2'}</answer>", False)


def synthetic_verify(stated_answer: str, snippet: str, _timeout_s: float) -> Verification:
    """Stand-in for `verify_attack`: the scripted snippet is `print(N)`, so no subprocess."""
    printed = _SNIPPET.fullmatch(snippet.strip())
    if printed is None:
        return Verification(False, "unsupported synthetic snippet")
    if not answers_match(printed.group(1), stated_answer):
        return Verification(False, f"mismatch: snippet printed {printed.group(1)!r}")
    return Verification(True, "ok")


def play_synthetic(
    skills: tuple[Skill, Skill], difficulty: float, matches: int, seed: int
) -> list[MatchRecord]:
    rng = random.Random(seed)
    a = Fighter("synthetic-a", "synthetic", "synthetic", "")
    b = Fighter("synthetic-b", "synthetic", "synthetic", "")
    llm = SyntheticLlm({a.name: skills[0], b.name: skills[1]}, difficulty, rng)
    return [
        run_match(a, b, llm.complete, _SETTINGS, BattleLog(f"synthetic_{i}"), rng, synthetic_verify)
        for i in range(matches)
    ]


def sweep(matches: int, difficulty: float, seed: int) -> dict[tuple[float, float], float]:
    """Attacker win rate per turn when both fighters share a skill and an attack bonus."""
    rates = {}
    for level in SKILLS:
        for bonus in ADVANTAGES:
            skill = Skill(level, bonus)
            records = play_synthetic((skill, skill), difficulty, matches, seed)
            rates[(level, bonus)] = compute_stats(records).attacker_win_rate
    return rates


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
            mark = "*" if max(rate, 1.0 - rate) <= GATE_MAX_ROLE_WIN_RATE else ""
            cells.append(f"{rate:.0%}{mark}".ljust(width))
        lines.append(f"{level:<7.1f}" + "".join(cells))
    return "\n".join(lines)
