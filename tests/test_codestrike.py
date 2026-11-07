import pytest

from arena.codestrike import MAX_TESTS, harness, validate
from arena.models import Attack, Fighter
from arena.prompts import (
    ATTACK_REQUEST,
    CODE_ATTACK_REQUEST,
    CODE_TOPICS,
    ParseError,
    attack_prompts,
    correction_prompt,
    defense_prompts,
    parse_attack,
    parse_code_defense,
    unparsed_prompt,
)
from arena.verifier import run_local, verify_attack

FIGHTER = Fighter("alpha", "groq", "some-model", "You are a careful coder.")
ADD = "def solve(a, b):\n    return a + b"


def run(solution: str, inputs: str) -> tuple[int, str]:
    result = run_local(harness(solution, inputs), 10.0)
    return result.returncode, result.stdout.strip()


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ("[[1, 2], [3, 4]]", "[3, 7]"),
        ("[[1]]", '["a"]'),
        ("[[]]", "[[1, [2, null]]]"),
        ("[[true], [false]]", "[true, false]"),
    ],
)
def test_valid_tests_pass(inputs: str, expected: str) -> None:
    validate(inputs, expected)


@pytest.mark.parametrize(
    ("inputs", "expected", "problem"),
    [
        ("not json", "[1]", "inputs"),
        ('{"a": 1}', "[1]", "list"),
        ("[]", "[]", "at least one"),
        ("[1, 2]", "[1, 2]", "argument list"),
        ("[[1], [2]]", "[1]", "same number"),
        ("[[1]]", "nope", "outputs"),
        ("[[1.5]]", "[1]", "float"),
        ("[[1]]", "[1.5]", "float"),
        (
            f"[{', '.join(['[1]'] * (MAX_TESTS + 1))}]",
            f"[{', '.join(['1'] * (MAX_TESTS + 1))}]",
            "most",
        ),
        (f"[[{'1' * 30000}]]", "[1]", "long"),
    ],
)
def test_bad_tests_are_rejected(inputs: str, expected: str, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        validate(inputs, expected)


def test_the_harness_prints_the_results_as_json() -> None:
    assert run(ADD, "[[1, 2], [3, 4]]") == (0, "[3, 7]")


def test_prints_inside_the_solution_do_not_reach_the_result() -> None:
    noisy = "def solve(a):\n    print('debug')\n    return a * 2"

    assert run(noisy, "[[1], [5]]") == (0, "[2, 10]")


def test_tuples_and_dicts_come_back_as_json() -> None:
    assert run("def solve(n):\n    return (n, {'k': [n]})", "[[1]]") == (0, '[[1, {"k": [1]}]]')


@pytest.mark.parametrize(
    "solution",
    [
        "def solve(a):\n    raise ValueError('boom')",
        "x = 1",
        "def solve(a):\n    return {1, 2}",
        "def solve(a:",
    ],
)
def test_a_crash_a_missing_function_or_unserialisable_output_fails_the_run(solution: str) -> None:
    code, out = run(solution, "[[1]]")

    assert code != 0 and out == ""


def test_the_harness_is_checked_like_any_other_snippet() -> None:
    inputs = "[[1, 2], [3, 4]]"

    assert verify_attack("[3, 7]", harness(ADD, inputs), 10.0).passed
    assert verify_attack("[3,7]", harness(ADD, inputs), 10.0).passed
    assert not verify_attack("[3, 8]", harness(ADD, inputs), 10.0).passed
    assert not verify_attack(
        "[3, 7]", harness("def solve(a, b):\n    return a - b", inputs), 10.0
    ).passed


def test_code_attack_prompts_ask_for_a_function_tests_and_outputs() -> None:
    system, user = attack_prompts(FIGHTER, "strings", [], domain="code")

    assert "careful coder" in system and "solve" in system
    assert user.endswith(CODE_ATTACK_REQUEST) and CODE_ATTACK_REQUEST != ATTACK_REQUEST
    for tag in ("<problem>", "<code>", "<tests>", "<answer>"):
        assert tag in CODE_ATTACK_REQUEST


def test_code_topics_are_not_the_math_topics() -> None:
    assert CODE_TOPICS and "strings" in CODE_TOPICS


CODE_REPLY = (
    "<problem>Add two numbers with solve(a, b).</problem>\n"
    "<code>```python\n" + ADD + "\n```</code>\n"
    "<tests>[[1, 2], [3, 4]]</tests>\n<answer>[3, 7]</answer>"
)


def test_parse_a_code_attack() -> None:
    attack = parse_attack(CODE_REPLY, domain="code")

    assert attack == Attack(
        "Add two numbers with solve(a, b).", "[3, 7]", ADD, domain="code", inputs="[[1, 2], [3, 4]]"
    )


@pytest.mark.parametrize(
    "bad",
    [
        CODE_REPLY.replace("<tests>[[1, 2], [3, 4]]</tests>", ""),
        CODE_REPLY.replace("[[1, 2], [3, 4]]", "oops"),
        CODE_REPLY.replace("[3, 7]", "[3]"),
        CODE_REPLY.replace("[3, 7]", "[3.5, 7]"),
    ],
)
def test_an_unusable_code_attack_is_a_parse_error(bad: str) -> None:
    with pytest.raises(ParseError):
        parse_attack(bad, domain="code")


def test_a_math_reply_is_still_parsed_as_math_by_default() -> None:
    attack = parse_attack("<problem>p</problem><answer>1</answer><code>print(1)</code>")

    assert (attack.domain, attack.inputs) == ("math", "")


def test_a_correction_for_a_code_attack_shows_the_tests_and_keeps_the_code_format_last() -> None:
    _, user = attack_prompts(FIGHTER, "strings", [], domain="code")
    attack = parse_attack(CODE_REPLY, domain="code")

    note = correction_prompt(user, attack, "mismatch: printed [3, 8]")

    assert "<tests>[[1, 2], [3, 4]]</tests>" in note
    assert note.endswith(CODE_ATTACK_REQUEST) and note.count(CODE_ATTACK_REQUEST) == 1


def test_an_unparsed_note_keeps_the_code_format_last() -> None:
    _, user = attack_prompts(FIGHTER, "strings", [], domain="code")

    note = unparsed_prompt(user, truncated=True)

    assert note.endswith(CODE_ATTACK_REQUEST) and note.count(CODE_ATTACK_REQUEST) == 1


def test_the_defender_is_asked_for_a_function_not_an_answer() -> None:
    system, user = defense_prompts(FIGHTER, "Add two numbers.", domain="code")

    assert "careful coder" in system and "solve" in system
    assert "Add two numbers." in user and "<code>" in system + user


def test_parse_a_code_defense_with_and_without_a_fence() -> None:
    assert parse_code_defense(f"<code>{ADD}</code>") == ADD
    assert parse_code_defense(f"<code>```python\n{ADD}\n```</code>") == ADD
    with pytest.raises(ParseError):
        parse_code_defense("I would add them.")


@pytest.mark.parametrize("label", ["python", "Python", "python "])
def test_a_language_label_copied_from_the_format_is_dropped(label: str) -> None:
    labelled = f"<code>{label}\n{ADD}</code>"

    assert parse_code_defense(labelled) == ADD
    assert parse_attack(CODE_REPLY.replace("<code>```python\n", f"<code>{label}\n"), "code").snippet
    assert parse_attack(f"<problem>p</problem><answer>1</answer>{labelled}").snippet == ADD


def test_code_that_merely_starts_with_python_in_a_name_is_kept() -> None:
    source = "python_version = 3\ndef solve():\n    return python_version"

    assert parse_code_defense(f"<code>{source}</code>") == source


def test_the_code_format_does_not_open_with_a_language_name() -> None:
    line = next(x for x in CODE_ATTACK_REQUEST.splitlines() if x.startswith("<code>"))

    assert not line.removeprefix("<code>").lower().startswith("python")
