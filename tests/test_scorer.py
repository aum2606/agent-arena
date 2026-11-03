import threading

from arena.config import Settings
from arena.damage import DIFFICULTY
from arena.llm import Completion, LlmError, LlmTimeout
from arena.models import Attack, Fighter
from arena.scorer import score_problem

SETTINGS = Settings(
    turn_time_limit_s=30.0,
    turn_max_tokens=256,
    defender_max_tokens=128,
    snippet_timeout_s=5.0,
    call_delay_s=0.0,
    max_retries=0,
    backoff_base_s=0.0,
)
PANEL = tuple(Fighter(f"ref-{i}", "p", f"m{i}", "a careful solver") for i in (1, 2, 3))
ATTACK = Attack("What is 6 * 7?", "42", "print(42)")
SOLVED = Completion("<answer>42</answer>", False)
WRONG = Completion("<answer>41</answer>", False)


def panel_replies(*replies: Completion | Exception):
    """A `complete` that hands each panel member its reply, matched by name (ref-1, ref-2, ...)."""
    by_name = {member.name: reply for member, reply in zip(PANEL, replies, strict=True)}

    def complete(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        reply = by_name[fighter.name]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return complete


def test_a_problem_every_member_solves_is_the_easiest() -> None:
    scored = score_problem(PANEL, ATTACK, panel_replies(SOLVED, SOLVED, SOLVED), SETTINGS)

    assert (scored.difficulty, scored.failed, scored.answered) == (0.5, 0, 3)
    assert [m.result for m in scored.members] == ["solved"] * 3


def test_a_problem_every_member_gets_wrong_is_the_hardest() -> None:
    scored = score_problem(PANEL, ATTACK, panel_replies(WRONG, WRONG, WRONG), SETTINGS)

    assert (scored.difficulty, scored.failed, scored.answered) == (2.0, 3, 3)


def test_two_of_three_failing_is_in_between() -> None:
    scored = score_problem(PANEL, ATTACK, panel_replies(SOLVED, WRONG, WRONG), SETTINGS)

    assert (scored.difficulty, scored.failed) == (1.5, 2)
    assert [(m.name, m.result) for m in scored.members] == [
        ("ref-1", "solved"),
        ("ref-2", "failed"),
        ("ref-3", "failed"),
    ]


def test_a_timeout_a_cut_off_reply_or_no_answer_counts_as_failing_like_a_defender() -> None:
    complete = panel_replies(
        LlmTimeout("slow"), Completion("<answer>42</answer>", True), Completion("no tags", False)
    )

    scored = score_problem(PANEL, ATTACK, complete, SETTINGS)

    assert (scored.difficulty, scored.failed, scored.answered) == (2.0, 3, 3)


def test_a_provider_error_leaves_that_member_out_instead_of_counting_against_the_problem() -> None:
    complete = panel_replies(LlmError("rate limited after 8 retries"), SOLVED, SOLVED)

    scored = score_problem(PANEL, ATTACK, complete, SETTINGS)

    assert (scored.difficulty, scored.failed, scored.answered) == (0.5, 0, 2)
    assert scored.members[0].result == "error"


def test_when_nobody_answers_the_problem_keeps_the_default_difficulty() -> None:
    errors = [LlmError("down")] * 3

    scored = score_problem(PANEL, ATTACK, panel_replies(*errors), SETTINGS)

    assert (scored.difficulty, scored.answered) == (DIFFICULTY, 0)


def test_members_get_the_defenders_prompt_and_token_budget() -> None:
    calls: list[tuple[str, str, int]] = []

    def complete(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        calls.append((system, user, max_tokens))
        return SOLVED

    score_problem(PANEL, ATTACK, complete, SETTINGS)

    assert len(calls) == 3
    for system, user, max_tokens in calls:
        assert "a careful solver" in system
        assert "What is 6 * 7?" in user and "6 * 7" in user
        assert "<answer>" in user
        assert max_tokens == SETTINGS.defender_max_tokens


def test_tokens_are_summed_over_the_members_that_reported_them() -> None:
    complete = panel_replies(
        Completion("<answer>42</answer>", False, 10),
        Completion("<answer>42</answer>", False, 25),
        Completion("<answer>42</answer>", False, None),
    )

    assert score_problem(PANEL, ATTACK, complete, SETTINGS).tokens == 35


def test_members_are_asked_at_the_same_time() -> None:
    # Each call waits for all three: sequential asking would time the barrier out and fail.
    barrier = threading.Barrier(3, timeout=5)

    def complete(fighter: Fighter, system: str, user: str, max_tokens: int) -> Completion:
        barrier.wait()
        return SOLVED

    scored = score_problem(PANEL, ATTACK, complete, SETTINGS)

    assert scored.answered == 3
