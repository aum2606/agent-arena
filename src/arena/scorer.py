from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from arena.config import Settings
from arena.damage import DIFFICULTY, difficulty_from_panel
from arena.llm import Complete, LlmError, LlmTimeout
from arena.models import Attack, Fighter
from arena.prompts import ParseError, defense_prompts, parse_defense
from arena.verifier import answers_match


@dataclass(frozen=True)
class MemberResult:
    name: str
    result: Literal["solved", "failed", "error"]
    tokens: int | None


@dataclass(frozen=True)
class Scored:
    difficulty: float
    failed: int
    answered: int  # members that gave a verdict; "error" members are not counted
    tokens: int  # what the panel spent on this problem (members that reported usage)
    members: list[MemberResult]


def _ask(member: Fighter, attack: Attack, complete: Complete, settings: Settings) -> MemberResult:
    """One member solves the problem under the defender's budget, as a defender would."""
    try:
        reply = complete(
            member, *defense_prompts(member, attack.problem), settings.defender_max_tokens
        )
    except LlmTimeout:
        return MemberResult(member.name, "failed", None)
    except LlmError:
        # A rate limit says nothing about the problem, so this member does not vote.
        return MemberResult(member.name, "error", None)
    if reply.truncated:
        return MemberResult(member.name, "failed", reply.tokens)
    try:
        given = parse_defense(reply.text)
    except ParseError:
        return MemberResult(member.name, "failed", reply.tokens)
    solved = answers_match(given, attack.answer)
    return MemberResult(member.name, "solved" if solved else "failed", reply.tokens)


def score_problem(
    panel: Sequence[Fighter], attack: Attack, complete: Complete, settings: Settings
) -> Scored:
    """Difficulty of a verified problem: the more of the panel fails it, the harder it is."""
    # Members are independent and wait on the network, so they are asked at the same time.
    with ThreadPoolExecutor(max_workers=max(len(panel), 1)) as pool:
        members = list(pool.map(lambda m: _ask(m, attack, complete, settings), panel))
    failed = sum(m.result == "failed" for m in members)
    answered = sum(m.result != "error" for m in members)
    difficulty = difficulty_from_panel(failed, answered) if answered else DIFFICULTY
    tokens = sum(m.tokens or 0 for m in members)
    return Scored(difficulty, failed, answered, tokens, members)
