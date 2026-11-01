import pytest

from arena.models import Attack, Fighter
from arena.prompts import (
    ATTACK_REQUEST,
    ParseError,
    attack_prompts,
    correction_prompt,
    defense_prompts,
    parse_attack,
    parse_defense,
)

TOPIC = "number theory"
FIGHTER = Fighter("alpha", "groq", "some-model", "You are a ruthless number theorist.")


def test_attack_prompts_carry_persona_and_reply_format() -> None:
    system, user = attack_prompts(FIGHTER, TOPIC, [])

    assert "ruthless number theorist" in system
    for tag in ("<problem>", "<answer>", "<code>"):
        assert tag in system + user


def test_defense_prompts_carry_persona_problem_and_reply_format() -> None:
    system, user = defense_prompts(FIGHTER, "What is 2 + 2?")

    assert "ruthless number theorist" in system
    assert "What is 2 + 2?" in user
    assert "<answer>" in system + user


def test_parse_attack_extracts_all_three_parts() -> None:
    text = "<problem>What is 6 * 7?</problem>\n<answer>42</answer>\n<code>print(6 * 7)</code>"

    assert parse_attack(text) == Attack("What is 6 * 7?", "42", "print(6 * 7)")


def test_parse_attack_ignores_chatter_and_strips_code_fences() -> None:
    text = (
        "Sure! Here is my attack.\n"
        "<problem>Sum 1..3</problem><answer> 6 </answer>\n"
        "<code>\n```python\nx = 'a\"b'\nprint(1 + 2 + 3)\n```\n</code>\nGood luck!"
    )

    attack = parse_attack(text)

    assert attack.answer == "6"
    assert attack.snippet == "x = 'a\"b'\nprint(1 + 2 + 3)"


@pytest.mark.parametrize("missing", ["problem", "answer", "code"])
def test_parse_attack_names_the_missing_part(missing: str) -> None:
    parts = {"problem": "P", "answer": "1", "code": "print(1)"}
    del parts[missing]
    text = "".join(f"<{k}>{v}</{k}>" for k, v in parts.items())

    with pytest.raises(ParseError, match=missing):
        parse_attack(text)


def test_parse_attack_rejects_empty_part() -> None:
    with pytest.raises(ParseError, match="answer"):
        parse_attack("<problem>P</problem><answer>  </answer><code>print(1)</code>")


def test_parse_defense_extracts_the_answer() -> None:
    assert parse_defense("Let me think... <answer> 3/4 </answer>") == "3/4"


def test_parse_defense_uses_the_last_answer_tag() -> None:
    assert parse_defense("<answer>draft</answer> wait, no: <answer>7</answer>") == "7"


def test_parse_defense_without_tag_is_an_error() -> None:
    with pytest.raises(ParseError, match="answer"):
        parse_defense("I think it is 7")


def test_attack_request_asks_for_code_before_answer() -> None:
    _, user = attack_prompts(FIGHTER, TOPIC, [])

    assert user.index("<code>") < user.index("<answer>")


def test_attack_rules_warn_against_unevaluated_output() -> None:
    system, _ = attack_prompts(FIGHTER, TOPIC, [])

    assert "Integral(" in system
    assert "doit()" in system


def test_attack_rules_allow_working_before_the_tags() -> None:
    system, _ = attack_prompts(FIGHTER, TOPIC, [])

    assert "step by step" in system


def test_both_roles_are_told_how_to_write_constants() -> None:
    for system in (attack_prompts(FIGHTER, TOPIC, [])[0], defense_prompts(FIGHTER, "P")[0]):
        assert "Euler's number is E" in system


def test_attack_prompt_names_this_turns_topic() -> None:
    _, user = attack_prompts(FIGHTER, "combinatorics", [])

    assert "combinatorics" in user


def test_attack_prompt_lists_problems_already_posed_and_forbids_repeats() -> None:
    _, user = attack_prompts(FIGHTER, TOPIC, ["Sum 1..10", "Find gcd(12, 18)"])

    assert "Sum 1..10" in user
    assert "Find gcd(12, 18)" in user
    assert "Do not repeat" in user


def test_attack_prompt_without_history_has_no_history_section() -> None:
    _, user = attack_prompts(FIGHTER, TOPIC, [])

    assert "already posed" not in user


def test_reply_format_is_still_the_end_of_the_attack_prompt() -> None:
    _, user = attack_prompts(FIGHTER, TOPIC, ["P"])

    assert user.endswith(ATTACK_REQUEST)


def test_attack_rules_demand_multi_step_problems_with_a_trap() -> None:
    system, _ = attack_prompts(FIGHTER, TOPIC, [])

    assert "at least three distinct steps" in system
    assert "textbook formula" in system
    assert "trap" in system


def test_attack_rules_suggest_designing_backwards_from_a_known_result() -> None:
    system, _ = attack_prompts(FIGHTER, TOPIC, [])

    assert "Design backwards" in system


def test_attack_rules_no_longer_steer_toward_standard_closed_forms() -> None:
    system, _ = attack_prompts(FIGHTER, TOPIC, [])

    assert "exact closed forms" not in system


def test_attack_prompt_without_outcomes_has_no_feedback_section() -> None:
    _, user = attack_prompts(FIGHTER, TOPIC, [])

    assert "How your last" not in user


def test_attack_prompt_summarises_how_recent_problems_fared() -> None:
    outcomes = ["block", "block", "hit", "backfire"]

    _, user = attack_prompts(FIGHTER, TOPIC, [], outcomes)

    assert "How your last 4 problems fared" in user
    assert "blocked by your opponent (too easy): 2" in user
    assert "failed your own check (too hard): 1" in user
    assert "hit your opponent: 1" in user
    assert "about a third" in user
    assert user.endswith(ATTACK_REQUEST)


def test_attack_prompt_only_counts_the_most_recent_window() -> None:
    outcomes = ["backfire"] * 5 + ["block"] * 10

    _, user = attack_prompts(FIGHTER, TOPIC, [], outcomes)

    assert "How your last 10 problems fared" in user
    assert "blocked by your opponent (too easy): 10" in user
    assert "failed your own check (too hard): 0" in user


def test_correction_prompt_shows_the_failed_attack_and_why_it_failed() -> None:
    user = attack_prompts(FIGHTER, TOPIC, [])[1]
    attack = Attack("What is 6 * 7?", "41", "print(42)")

    text = correction_prompt(user, attack, "mismatch: snippet printed '42', stated '41'")

    assert text.startswith(user.removesuffix(ATTACK_REQUEST))
    assert text.endswith(ATTACK_REQUEST)  # the reply format stays last, as in the first prompt
    for part in ("What is 6 * 7?", "print(42)", "41", "snippet printed '42', stated '41'"):
        assert part in text
