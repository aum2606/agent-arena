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


@dataclass(frozen=True)
class _Answer:
    name: str
    status: Literal["answered", "failed", "error"]
    text: str | None  # the parsed answer, when answered
    tokens: int | None


def _solve(member: Fighter, attack: Attack, complete: Complete, settings: Settings) -> _Answer:
    """One member solves the problem under the defender's budget, as a defender would."""
    try:
        reply = complete(
            member, *defense_prompts(member, attack.problem), settings.defender_max_tokens
        )
    except LlmTimeout:
        return _Answer(member.name, "failed", None, None)
    except LlmError:
        # A rate limit says nothing about the problem, so this member does not vote.
        return _Answer(member.name, "error", None, None)
    if reply.truncated:
        return _Answer(member.name, "failed", None, reply.tokens)
    try:
        given = parse_defense(reply.text)
    except ParseError:
        return _Answer(member.name, "failed", None, reply.tokens)
    return _Answer(member.name, "answered", given, reply.tokens)


def _ask(member: Fighter, attack: Attack, complete: Complete, settings: Settings) -> MemberResult:
    answer = _solve(member, attack, complete, settings)
    if answer.text is None:
        return MemberResult(
            answer.name, "error" if answer.status == "error" else "failed", answer.tokens
        )
    solved = answers_match(answer.text, attack.answer)
    return MemberResult(answer.name, "solved" if solved else "failed", answer.tokens)


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


@dataclass(frozen=True)
class ReviewMember:
    name: str
    verdict: Literal["defender", "attacker", "neither", "none"]  # whose answer it gave, or none
    tokens: int | None


@dataclass(frozen=True)
class Review:
    overturned: bool
    answered: int  # members that gave an answer
    for_defender: int
    for_attacker: int
    tokens: int
    members: list[ReviewMember]


def review_hit(
    panel: Sequence[Fighter],
    attack: Attack,
    defender_answer: str,
    complete: Complete,
    settings: Settings,
) -> Review:
    """Before a defender takes a hit, the panel solves the problem. The attacker's snippet only
    proves its answer agrees with itself, so a deliberately wrong answer always verifies (D-069):
    if most of the members who answered (at least two) gave the defender's answer, the hit is
    overturned. A member that errors, times out, is cut off or gives no answer does not vote."""
    with ThreadPoolExecutor(max_workers=max(len(panel), 1)) as pool:
        answers = list(pool.map(lambda m: _solve(m, attack, complete, settings), panel))
    members = []
    for a in answers:
        verdict: Literal["defender", "attacker", "neither", "none"] = "none"
        if a.text is not None:
            if answers_match(a.text, defender_answer):
                verdict = "defender"
            elif answers_match(a.text, attack.answer):
                verdict = "attacker"
            else:
                verdict = "neither"
        members.append(ReviewMember(a.name, verdict, a.tokens))
    answered = sum(m.verdict != "none" for m in members)
    for_defender = sum(m.verdict == "defender" for m in members)
    return Review(
        overturned=answered >= 2 and for_defender * 2 > answered,
        answered=answered,
        for_defender=for_defender,
        for_attacker=sum(m.verdict == "attacker" for m in members),
        tokens=sum(m.tokens or 0 for m in members),
        members=members,
    )
