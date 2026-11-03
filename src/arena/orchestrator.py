import random
from collections.abc import Callable, Sequence
from typing import Literal

from arena.battle_log import BattleLog
from arena.config import Settings
from arena.damage import (
    BASE_DAMAGE,
    DIFFICULTY,
    MAX_TURNS,
    STARTING_HP,
    apply_damage,
    backfire_damage,
    damage,
    match_result,
)
from arena.llm import Complete, Completion, LlmTimeout
from arena.models import Attack, Fighter, MatchRecord, Outcome, Side, TurnResult
from arena.prompts import (
    TOPICS,
    ParseError,
    attack_prompts,
    correction_prompt,
    defense_prompts,
    parse_attack,
    parse_defense,
)
from arena.scorer import score_problem
from arena.verifier import Verification, answers_match, verify_attack

# (stated answer, snippet, timeout in seconds); the synthetic simulator swaps in a fast stand-in.
Verify = Callable[[str, str, float], Verification]


class _Backfire(Exception):
    """The attack failed; `attack` is the last parsed attempt, if any (for the log)."""

    def __init__(self, reason: str, attack: Attack | None = None) -> None:
        super().__init__(reason)
        self.attack = attack


def _attempt(attack: Attack) -> dict[str, str]:
    return {"problem": attack.problem, "answer": attack.answer, "code": attack.snippet}


def _other(side: Side) -> Side:
    return "b" if side == "a" else "a"


def _draft(
    attacker: Fighter,
    side: Side,
    prompts: tuple[str, str],
    complete: Complete,
    settings: Settings,
    log: BattleLog,
) -> Attack:
    """One attacker reply, parsed. A timeout or malformed reply raises _Backfire."""
    try:
        reply = complete(attacker, *prompts, settings.turn_max_tokens)
    except LlmTimeout as exc:
        log.emit("timeout", actor=side)
        raise _Backfire(str(exc)) from exc
    try:
        return parse_attack(reply.text)
    except ParseError as exc:
        raise _Backfire(str(exc)) from exc


def _pose_attack(
    attacker: Fighter,
    side: Side,
    prompts: tuple[str, str],
    complete: Complete,
    verify: Verify,
    settings: Settings,
    log: BattleLog,
) -> Attack:
    """Get a verified attack or raise _Backfire. Other provider errors abort the match.

    A failed check gets one retry that shows the attacker the real result (D-025): models guess the
    answer without running their snippet, so most first attempts miss.
    """
    attack = _draft(attacker, side, prompts, complete, settings, log)
    check = verify(attack.answer, attack.snippet, settings.snippet_timeout_s)
    if check.passed:
        return attack
    log.emit("attack_retry", actor=side, reason=check.reason, **_attempt(attack))
    system, user = prompts
    retry_prompts = (system, correction_prompt(user, attack, check.reason))
    attack = _draft(attacker, side, retry_prompts, complete, settings, log)
    check = verify(attack.answer, attack.snippet, settings.snippet_timeout_s)
    if not check.passed:
        raise _Backfire(check.reason, attack)
    return attack


def _defend(
    defender: Fighter,
    side: Side,
    attack: Attack,
    complete: Complete,
    settings: Settings,
    log: BattleLog,
) -> float:
    """Returns the defender's score: 1.0 for a correct answer, else 0.0."""
    try:
        reply: Completion | None = complete(
            defender, *defense_prompts(defender, attack.problem), settings.defender_max_tokens
        )
    except LlmTimeout:
        reply = None
    if reply is None or reply.truncated:
        log.emit("timeout", actor=side)
        return 0.0
    try:
        given = parse_defense(reply.text)
    except ParseError as exc:
        log.emit("defend_result", actor=side, score=0.0, answer=None, reason=str(exc))
        return 0.0
    score = 1.0 if answers_match(given, attack.answer) else 0.0
    log.emit("defend_result", actor=side, score=score, answer=given)
    return score


def _hit(log: BattleLog, turn: int, attacker: Side, target: Side, amount: float) -> TurnResult:
    log.emit("hit", target=target, damage=amount)
    outcome: Literal["hit", "backfire"] = "backfire" if target == attacker else "hit"
    return TurnResult(turn, attacker, outcome, target, amount)


def play_turn(
    turn: int,
    attacker_side: Side,
    fighters: dict[Side, Fighter],
    complete: Complete,
    verify: Verify,
    settings: Settings,
    log: BattleLog,
    topic: str,
    used_problems: list[str],
    recent_outcomes: list[Outcome],
    panel: Sequence[Fighter] = (),
) -> TurnResult:
    """Plays one turn; a verified problem is appended to `used_problems`."""
    defender_side = _other(attacker_side)
    log.start_turn(turn)
    log.emit("attack_start", actor=attacker_side)
    try:
        fighter = fighters[attacker_side]
        prompts = attack_prompts(fighter, topic, used_problems, recent_outcomes)
        attack = _pose_attack(fighter, attacker_side, prompts, complete, verify, settings, log)
    except _Backfire as exc:
        log.emit(
            "backfire",
            actor=attacker_side,
            reason=str(exc),
            **(_attempt(exc.attack) if exc.attack else {}),
        )
        amount = backfire_damage(BASE_DAMAGE, DIFFICULTY)
        return _hit(log, turn, attacker_side, attacker_side, amount)
    used_problems.append(attack.problem)
    log.emit("attack_verified", actor=attacker_side, **_attempt(attack))
    difficulty = DIFFICULTY
    if panel:
        scored = score_problem(panel, attack, complete, settings)
        difficulty = scored.difficulty
        log.emit(
            "difficulty",
            value=scored.difficulty,
            failed=scored.failed,
            answered=scored.answered,
            tokens=scored.tokens,
            panel=[
                {"name": m.name, "result": m.result, "tokens": m.tokens} for m in scored.members
            ],
        )
    log.emit("defend_start", actor=defender_side)
    score = _defend(fighters[defender_side], defender_side, attack, complete, settings, log)
    if score == 1.0:
        log.emit("block", actor=defender_side)
        return TurnResult(turn, attacker_side, "block", defender_side, 0.0)
    return _hit(log, turn, attacker_side, defender_side, damage(BASE_DAMAGE, difficulty, 0.0))


def run_match(
    fighter_a: Fighter,
    fighter_b: Fighter,
    complete: Complete,
    settings: Settings,
    log: BattleLog,
    rng: random.Random,
    verify: Verify = verify_attack,
    history: dict[Side, list[Outcome]] | None = None,
    max_turns: int = MAX_TURNS,
    panel: Sequence[Fighter] = (),
) -> MatchRecord:
    """Fighter A attacks first and roles swap every turn. `rng` picks each turn's topic."""
    log.record_fighters(fighter_a, fighter_b)
    used_problems: list[str] = []
    # Each fighter's own attack outcomes, earlier matches first (copied: the caller's stay intact).
    outcomes: dict[Side, list[Outcome]] = {"a": [], "b": []}
    for side, earlier in (history or {}).items():
        outcomes[side] = list(earlier)
    fighters: dict[Side, Fighter] = {"a": fighter_a, "b": fighter_b}
    hp: dict[Side, float] = {"a": STARTING_HP, "b": STARTING_HP}
    turns: list[TurnResult] = []
    turn = 0
    while True:
        turn += 1
        attacker_side: Side = "a" if turn % 2 == 1 else "b"
        topic = rng.choice(TOPICS)
        result = play_turn(
            turn,
            attacker_side,
            fighters,
            complete,
            verify,
            settings,
            log,
            topic,
            used_problems,
            outcomes[attacker_side],
            panel,
        )
        turns.append(result)
        outcomes[attacker_side].append(result.outcome)
        hp[result.target] = apply_damage(hp[result.target], result.damage)
        log.emit("hp", a=hp["a"], b=hp["b"])
        if hp[result.target] <= 0:
            log.emit("knockout", target=result.target)
        outcome = match_result(hp["a"], hp["b"], turn, max_turns)
        if outcome is not None:
            log.emit("match_end", winner=outcome.winner, reason=outcome.reason, turns=turn)
            return MatchRecord(fighter_a.name, fighter_b.name, turns, hp["a"], hp["b"], outcome)
