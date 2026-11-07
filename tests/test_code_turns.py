import random
from dataclasses import replace
from typing import Any

import pytest

from arena.battle_log import BattleLog
from arena.config import Settings
from arena.llm import Completion
from arena.models import Fighter, MatchRecord
from arena.orchestrator import run_match
from arena.prompts import ATTACK_REQUEST, CODE_ATTACK_REQUEST, CODE_DEFENSE_REQUEST, CODE_TOPICS

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    defender_max_tokens=128,
    snippet_timeout_s=10.0,
    call_delay_s=0.0,
    max_retries=0,
    backoff_base_s=0.0,
    code_share=1.0,
)
A = Fighter("alice", "p", "m", "persona a")
B = Fighter("bob", "p", "m", "persona b")
ADD = "def solve(a, b):\n    return a + b"
SUB = "def solve(a, b):\n    return a - b"
TESTS = "[[1, 2], [3, 4]]"


def code_attack(expected: str = "[3, 7]", code: str = ADD) -> str:
    return (
        f"<problem>Add two numbers with solve(a, b).</problem><code>{code}</code>"
        f"<tests>{TESTS}</tests><answer>{expected}</answer>"
    )


def code_reply(code: str = ADD) -> str:
    return f"<code>{code}</code>"


def math_attack() -> str:
    return "<problem>6 * 7?</problem><answer>42</answer><code>print(42)</code>"


class CodeLlm:
    """Scripted fighters for matches that mix domains; `kinds` records what each call asked."""

    def __init__(self, attacks: dict[str, list[str]], defenses: dict[str, list[str]]) -> None:
        self.attacks = attacks
        self.defenses = defenses
        self.kinds: list[str] = []
        self.users: list[str] = []

    def __call__(self, fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        if user.endswith(CODE_ATTACK_REQUEST):
            self.kinds.append("code-attack")
            queue = self.attacks[fighter.name]
        elif user.endswith(ATTACK_REQUEST):
            self.kinds.append("math-attack")
            queue = self.attacks[fighter.name]
        else:
            self.kinds.append(
                "code-defense" if user.endswith(CODE_DEFENSE_REQUEST) else "math-defense"
            )
            queue = self.defenses[fighter.name]
        self.users.append(user)
        return Completion(queue.pop(0), False)


def play(
    llm: CodeLlm,
    settings: Settings = SETTINGS,
    rng: random.Random | None = None,
    panel: tuple[Fighter, ...] = (),
) -> tuple[MatchRecord, BattleLog]:
    log = BattleLog("m1")
    record = run_match(A, B, llm, settings, log, rng or random.Random(0), panel=panel)
    return record, log


def events(log: BattleLog, turn: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = log.to_dict()["turns"][turn - 1]["events"]
    return events


def of_type(log: BattleLog, turn: int, kind: str) -> dict[str, Any]:
    return next(e for e in events(log, turn) if e["type"] == kind)


def blocking_llm() -> CodeLlm:
    return CodeLlm(
        {"alice": [code_attack()] * 3, "bob": [code_attack()] * 3},
        {"alice": [code_reply()] * 3, "bob": [code_reply()] * 3},
    )


def test_a_correct_function_blocks_a_code_attack() -> None:
    record, log = play(blocking_llm())

    assert [t.outcome for t in record.turns] == ["block"] * 6
    verified = of_type(log, 1, "attack_verified")
    assert (verified["domain"], verified["tests"], verified["code"]) == ("code", TESTS, ADD)
    assert verified["answer"] == "[3, 7]"
    result = of_type(log, 1, "defend_result")
    assert (result["score"], result["answer"]) == (1.0, ADD)


def test_the_defender_is_never_shown_the_tests_or_the_expected_outputs() -> None:
    llm = blocking_llm()

    play(llm)

    defense_prompts = [u for k, u in zip(llm.kinds, llm.users, strict=True) if k == "code-defense"]
    assert defense_prompts
    for prompt in defense_prompts:
        assert TESTS not in prompt and "[3, 7]" not in prompt


def test_a_wrong_function_is_a_hit_that_says_what_failed() -> None:
    llm = CodeLlm(
        {"alice": [code_attack()] * 3, "bob": [code_attack()] * 3},
        {"alice": [code_reply(SUB)] * 3, "bob": [code_reply(SUB)] * 3},
    )

    record, log = play(llm)

    assert [t.outcome for t in record.turns] == ["hit"] * 6
    assert all(t.damage == 20.0 for t in record.turns)  # difficulty 1.0: no panel for code
    result = of_type(log, 1, "defend_result")
    assert result["score"] == 0.0 and result["reason"].startswith("mismatch")


def test_an_endless_function_is_a_hit() -> None:
    llm = CodeLlm(
        {"alice": [code_attack()] * 3, "bob": [code_attack()] * 3},
        {
            "alice": [code_reply()] * 3,
            "bob": [code_reply("def solve(a, b):\n    while True:\n        pass")]
            + [code_reply()] * 2,
        },
    )

    record, log = play(llm, replace(SETTINGS, snippet_timeout_s=0.5))

    assert record.turns[0].outcome == "hit"
    assert of_type(log, 1, "defend_result")["reason"].startswith("timeout")


def test_a_reply_without_code_scores_zero() -> None:
    llm = CodeLlm(
        {"alice": [code_attack()] * 3, "bob": [code_attack()] * 3},
        {"alice": [code_reply()] * 3, "bob": ["I would add them."] + [code_reply()] * 2},
    )

    record, log = play(llm)

    assert record.turns[0].outcome == "hit"
    result = of_type(log, 1, "defend_result")
    assert result["answer"] is None and "<code>" in result["reason"]


def test_a_wrong_stated_output_gets_one_retry_that_shows_the_tests() -> None:
    llm = CodeLlm(
        {"alice": [code_attack("[3, 8]"), code_attack()] + [code_attack()] * 2,
         "bob": [code_attack()] * 3},
        {"alice": [code_reply()] * 3, "bob": [code_reply()] * 3},
    )  # fmt: skip

    record, log = play(llm)

    assert record.turns[0].outcome == "block"
    retry = of_type(log, 1, "attack_retry")
    assert retry["reason"].startswith("mismatch") and retry["domain"] == "code"
    retry_prompt = llm.users[1]
    assert f"<tests>{TESTS}</tests>" in retry_prompt and retry_prompt.endswith(CODE_ATTACK_REQUEST)


def test_two_wrong_attacks_backfire_and_the_defender_is_never_asked() -> None:
    llm = CodeLlm(
        {"alice": [code_attack("[3, 8]")] * 2 + [code_attack()] * 2, "bob": [code_attack()] * 3},
        {"alice": [code_reply()] * 3, "bob": [code_reply()] * 2},
    )

    record, log = play(llm)

    assert record.turns[0].outcome == "backfire" and record.turns[0].damage == 10.0
    backfire = of_type(log, 1, "backfire")
    assert backfire["domain"] == "code" and backfire["tests"] == TESTS


def test_the_panel_does_not_score_code_problems() -> None:
    _, log = play(blocking_llm(), panel=(A,))

    assert all(e["type"] != "difficulty" for t in log.to_dict()["turns"] for e in t["events"])


class Scripted(random.Random):
    """A generator whose `random()` follows a script, to pick each turn's domain."""

    def __init__(self, values: list[float]) -> None:
        super().__init__(0)
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)

    def choice(self, seq: Any) -> Any:  # the stock choice would draw from random() too
        return seq[0]


def test_code_share_picks_the_domain_turn_by_turn_and_the_topic_from_its_list() -> None:
    llm = CodeLlm(
        {"alice": [code_attack()] * 3, "bob": [math_attack()] * 3},
        {"alice": ["<answer>42</answer>"] * 3, "bob": [code_reply()] * 3},
    )

    record, _ = play(
        llm, replace(SETTINGS, code_share=0.5), Scripted([0.1, 0.9, 0.1, 0.9, 0.1, 0.9])
    )

    assert [t.outcome for t in record.turns] == ["block"] * 6
    assert llm.kinds == ["code-attack", "code-defense", "math-attack", "math-defense"] * 3
    code_prompts = [u for k, u in zip(llm.kinds, llm.users, strict=True) if k == "code-attack"]
    assert all(any(f"Topic for this turn: {t}." in p for t in CODE_TOPICS) for p in code_prompts)


def test_without_code_share_the_domain_draw_never_happens() -> None:
    class Forbidden(random.Random):
        def random(self) -> float:
            raise AssertionError("the domain was drawn although code_share is 0")

        def choice(self, seq: Any) -> Any:
            return seq[0]

    llm = CodeLlm(
        {"alice": [math_attack()] * 3, "bob": [math_attack()] * 3},
        {"alice": ["<answer>42</answer>"] * 3, "bob": ["<answer>42</answer>"] * 3},
    )

    record, _ = play(llm, replace(SETTINGS, code_share=0.0), Forbidden(0))

    assert [t.outcome for t in record.turns] == ["block"] * 6


@pytest.mark.parametrize("kind", ["math-attack", "math-defense"])
def test_math_turns_never_use_the_code_formats(kind: str) -> None:
    llm = CodeLlm(
        {"alice": [math_attack()] * 3, "bob": [math_attack()] * 3},
        {"alice": ["<answer>42</answer>"] * 3, "bob": ["<answer>42</answer>"] * 3},
    )

    play(llm, replace(SETTINGS, code_share=0.0))

    assert set(llm.kinds) == {"math-attack", "math-defense"} and kind in llm.kinds
