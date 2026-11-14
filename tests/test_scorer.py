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


# The attacker's snippet confirms its own answer, so a deliberately wrong one verifies. When the
# defender is about to take a hit, the panel decides whose answer the problem favours (D-069).
FIRST_ATTACK = Attack("What is 6 * 7?", "41", "print(41)")  # wrong on purpose


def test_a_hit_is_overturned_when_most_of_the_panel_sides_with_the_defender() -> None:
    from arena.scorer import review_hit

    review = review_hit(PANEL, FIRST_ATTACK, "42", panel_replies(SOLVED, SOLVED, WRONG), SETTINGS)

    assert review.overturned and (review.answered, review.for_defender, review.for_attacker) == (
        3,
        2,
        1,
    )


def test_a_hit_stands_when_most_of_the_panel_sides_with_the_attacker() -> None:
    from arena.scorer import review_hit

    review = review_hit(PANEL, FIRST_ATTACK, "42", panel_replies(WRONG, WRONG, SOLVED), SETTINGS)

    assert not review.overturned and review.for_attacker == 2


def test_a_split_panel_does_not_overturn() -> None:
    from arena.scorer import review_hit

    other = Completion("<answer>7</answer>", False)
    review = review_hit(PANEL, FIRST_ATTACK, "42", panel_replies(SOLVED, WRONG, other), SETTINGS)

    assert not review.overturned


def test_one_answering_member_is_not_enough_to_overturn() -> None:
    from arena.scorer import review_hit

    review = review_hit(
        PANEL,
        FIRST_ATTACK,
        "42",
        panel_replies(SOLVED, LlmError("429"), LlmTimeout("slow")),
        SETTINGS,
    )

    assert not review.overturned and review.answered == 1


def test_two_answering_members_who_agree_with_the_defender_are_enough() -> None:
    from arena.scorer import review_hit

    review = review_hit(
        PANEL, FIRST_ATTACK, "42", panel_replies(SOLVED, SOLVED, LlmError("429")), SETTINGS
    )

    assert review.overturned and review.answered == 2


def test_members_who_ran_out_of_tokens_or_gave_no_answer_do_not_vote() -> None:
    from arena.scorer import review_hit

    cut = Completion("<answer>42", True)
    mush = Completion("no tags here", False)
    review = review_hit(PANEL, FIRST_ATTACK, "42", panel_replies(cut, mush, SOLVED), SETTINGS)

    assert review.answered == 1 and not review.overturned


def test_the_review_reports_each_members_verdict_and_what_the_panel_spent() -> None:
    from arena.scorer import review_hit

    done = Completion("<answer>42</answer>", False, tokens=100)
    review = review_hit(PANEL, FIRST_ATTACK, "42", panel_replies(done, WRONG, done), SETTINGS)

    assert [(m.name, m.verdict) for m in review.members] == [
        ("ref-1", "defender"),
        ("ref-2", "attacker"),
        ("ref-3", "defender"),
    ]
    assert review.tokens == 200
