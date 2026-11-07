import os
import time

import pytest
import sympy

from arena.safe_expr import MAX_CHARS, UnsafeAnswer, parse_answer
from arena.verifier import answers_match


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("42", sympy.Integer(42)),
        (" 42 ", sympy.Integer(42)),
        ("-5", sympy.Integer(-5)),
        ("1/3", sympy.Rational(1, 3)),
        ("2*3 + 4", sympy.Integer(10)),
        ("2**10", sympy.Integer(1024)),
        ("2^10", sympy.Integer(1024)),
        ("2**-1", sympy.Rational(1, 2)),
        ("10**9 + 7", sympy.Integer(1_000_000_007)),
        ("0.25", sympy.Float("0.25")),
        ("sqrt(8)", 2 * sympy.sqrt(2)),
        ("pi/3", sympy.pi / 3),
        ("E**2", sympy.E**2),
        ("2*I", 2 * sympy.I),
        ("100*arcsin(3/5) - 48", 100 * sympy.asin(sympy.Rational(3, 5)) - 48),
        ("asin(1)", sympy.pi / 2),
        ("factorial(5)", sympy.Integer(120)),
        ("binomial(10, 3)", sympy.Integer(120)),
        ("5*zeta(3)/8", 5 * sympy.zeta(3) / 8),
        ("gamma(5)", sympy.Integer(24)),
        ("gcd(12, 18)", sympy.Integer(6)),
        ("Abs(-3)", sympy.Integer(3)),
        ("abs(-3)", sympy.Integer(3)),
        ("Mod(7, 3)", sympy.Integer(1)),
        ("7 % 3", sympy.Integer(1)),
        ("Rational(1, 2)", sympy.Rational(1, 2)),
        ("x**2 - 1", sympy.Symbol("x") ** 2 - 1),
        ("(x - 1)*(x + 1)", (sympy.Symbol("x") - 1) * (sympy.Symbol("x") + 1)),
        ("log(E)", sympy.Integer(1)),
        ("2**n", 2 ** sympy.Symbol("n")),
    ],
)
def test_ordinary_answers_parse(text: str, value: sympy.Basic) -> None:
    assert sympy.simplify(parse_answer(text) - value) == 0


def test_infinity_is_a_name() -> None:
    assert parse_answer("oo") == sympy.oo


@pytest.mark.parametrize("text", ["True", "False"])
def test_booleans_are_not_numbers(text: str) -> None:
    with pytest.raises(UnsafeAnswer):
        parse_answer(text)


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('echo hi')",
        "__import__",
        "().__class__",
        "[x for x in range(3)]",
        "lambda: 1",
        "exec('1')",
        "eval('1')",
        "open('file')",
        "print(1)",
        "sympify('1')",
        "Symbol('x')",
        "S(1)",
        "N(1)",
        "os",
        "sympy",
        "x.y",
        "sqrt(2).evalf()",
        "(1).real",
        "x[0]",
        "{1: 2}",
        "x = 1",
        "'a'",
        '"a"',
        "1 if x else 2",
        "x; y",
        "x\n y",
        "f'{1}'",
        "5!",
        "sqrt(x=2)",
        "sqrt(*[2])",
        "True",
        "None",
        "_",
        "x_1",
        "xy",
        "theta",
        "",
        "   ",
        "1 +",
        "2 3",
    ],
)
def test_anything_but_plain_math_is_refused(text: str) -> None:
    with pytest.raises(UnsafeAnswer):
        parse_answer(text)


@pytest.mark.parametrize(
    "text",
    [
        "9**9**9",
        "10**10**10",
        "(9**99999)**99999",
        "2**100001",
        "x**1000",
        "factorial(10**8)",
        "factorial(100000)",
        "gamma(10**9)",
        "zeta(10**6)",
        "binomial(10**9, 5*10**8)",
        "gcd(10**1001, 3)",
        "log(2**100000)",
        "9**(9**9)",
        "sqrt(2)**100001",
        "1/0",
    ],
)
def test_expressions_that_would_hang_or_exhaust_memory_are_refused_quickly(text: str) -> None:
    start = time.monotonic()

    with pytest.raises(UnsafeAnswer):
        parse_answer(text)

    assert time.monotonic() - start < 1.0


def test_size_limits_on_the_text_and_the_expression() -> None:
    parse_answer("1" * 150)
    with pytest.raises(UnsafeAnswer, match="long"):
        parse_answer("1" * (MAX_CHARS + 1))
    with pytest.raises(UnsafeAnswer, match="large"):
        parse_answer("+".join(["x"] * 60))


def test_a_reply_cannot_run_code_in_the_worker() -> None:
    os.environ.pop("ARENA_EXPLOIT_PROBE", None)

    assert not answers_match(
        "__import__('os').environ.__setitem__('ARENA_EXPLOIT_PROBE', '1')", "1"
    )
    assert "ARENA_EXPLOIT_PROBE" not in os.environ


def test_a_hostile_answer_is_just_a_wrong_answer() -> None:
    assert not answers_match("9**9**9", "1")
    assert not answers_match("1", "__import__('os')")
    assert answers_match("2**100", "1267650600228229401496703205376")
