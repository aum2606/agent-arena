"""Turn the text of a model's answer into a SymPy value without ever running that text.

`sympy.parse_expr` evaluates strings, so a reply such as `__import__('os')...` ran inside the worker
that holds the database URL and every provider key, and `9**9**9` hung it (D-047). This module reads
the text with Python's `ast`, accepts only plain math, and builds the value bottom-up, refusing any
step that would be huge before it is computed.
"""

import ast
import re
from collections.abc import Callable
from typing import Any

import sympy

MAX_CHARS = 200
MAX_NODES = 150  # syntax-tree nodes, operators included; a ten-term polynomial is about 100
MAX_EXPONENT = 100_000
MAX_SYMBOLIC_EXPONENT = 200  # (x + 1)**n is expanded when two answers are compared
MAX_DIGITS = 100_000  # of any number built while evaluating: 2**100000 has 30,103
MAX_ARG_DIGITS = 1_000  # of a number passed to a function
MAX_FACTORIAL = 10_000  # the largest number factorial, binomial, gamma and zeta accept

# No underscores (so no dunder names), quotes, brackets, braces, `=`, `;`, `!` or backslashes.
_CHARS = re.compile(r"[A-Za-z0-9\s+\-*/%^().,]*")
_LOG10_2 = 0.30103


class UnsafeAnswer(ValueError):
    """The text is not plain math, or evaluating it would be too big."""


def _digits(value: Any) -> int:
    """Roughly how many decimal digits a number has (str() refuses very long integers)."""
    if isinstance(value, sympy.Rational):
        return int(max(abs(int(value.p)).bit_length(), int(value.q).bit_length()) * _LOG10_2) + 1
    return 1 if isinstance(value, sympy.Float) else 0


def _number_args(args: tuple[Any, ...]) -> list[Any]:
    return [a for a in args if isinstance(a, sympy.Number)]


def _check_args(args: tuple[Any, ...]) -> None:
    for number in _number_args(args):
        if _digits(number) > MAX_ARG_DIGITS:
            raise UnsafeAnswer("a number passed to a function is too large")


def _bounded(function: Callable[..., Any]) -> Callable[..., Any]:
    """For functions whose cost grows with the size of their argument (n! for a huge n hangs)."""

    def call(*args: Any) -> Any:
        if any(abs(x) > MAX_FACTORIAL for x in _number_args(args)):
            raise UnsafeAnswer("that function of a number that large would take too long")
        return function(*args)

    return call


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    **{
        name: getattr(sympy, name)
        for name in [
            "sqrt",
            "cbrt",
            "root",
            "exp",
            "log",
            "sin",
            "cos",
            "tan",
            "cot",
            "sec",
            "csc",
            "asin",
            "acos",
            "atan",
            "atan2",
            "sinh",
            "cosh",
            "tanh",
            "asinh",
            "acosh",
            "atanh",
            "gcd",
            "lcm",
            "Abs",
            "floor",
            "ceiling",
            "sign",
            "Mod",
            "Max",
            "Min",
            "Rational",
            "Integer",
        ]
    },
    "ln": sympy.log,
    "abs": sympy.Abs,
    "arcsin": sympy.asin,  # the standard spellings SymPy lacks (D-041)
    "arccos": sympy.acos,
    "arctan": sympy.atan,
    **{name: _bounded(getattr(sympy, name)) for name in ("factorial", "binomial", "gamma", "zeta")},
}
_CONSTANTS: dict[str, Any] = {
    "pi": sympy.pi,
    "E": sympy.E,
    "I": sympy.I,
    "oo": sympy.oo,
    "GoldenRatio": sympy.GoldenRatio,
    "EulerGamma": sympy.EulerGamma,
    "Catalan": sympy.Catalan,
}


def _pow(base: Any, exponent: Any) -> Any:
    if isinstance(exponent, sympy.Number) or not exponent.free_symbols:
        try:
            size = abs(float(sympy.N(exponent)))
        except (TypeError, ValueError) as exc:
            raise UnsafeAnswer("the exponent is not a usable number") from exc
        if size > (MAX_SYMBOLIC_EXPONENT if base.free_symbols else MAX_EXPONENT):
            raise UnsafeAnswer("the exponent is too large")
        if _digits(base) * max(size, 1) > MAX_DIGITS:
            raise UnsafeAnswer("the power would have too many digits")
    return base**exponent


def _binary(op: ast.operator, left: Any, right: Any) -> Any:
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if isinstance(op, ast.Div):
        return left / right
    if isinstance(op, ast.Pow):
        return _pow(left, right)
    if isinstance(op, ast.Mod):
        _check_args((left, right))
        return sympy.Mod(left, right)
    raise UnsafeAnswer(f"the operator {type(op).__name__} is not allowed")


def _eval(node: ast.expr) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):  # True and False are int subclasses, not numbers here
            raise UnsafeAnswer("only numbers are allowed as literals")
        if isinstance(node.value, int):
            return sympy.Integer(node.value)
        if isinstance(node.value, float) and node.value == node.value and abs(node.value) < 1e300:
            return sympy.Float(str(node.value))
        raise UnsafeAnswer("only numbers are allowed as literals")
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if len(node.id) == 1:
            return sympy.Symbol(node.id)
        raise UnsafeAnswer(f"the name {node.id!r} is not allowed")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        operand = _eval(node.operand)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        return _binary(node.op, _eval(node.left), _eval(node.right))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS or node.keywords:
            raise UnsafeAnswer("only the listed math functions may be called")
        args = tuple(_eval(arg) for arg in node.args)
        _check_args(args)
        return _FUNCTIONS[node.func.id](*args)
    raise UnsafeAnswer(f"{type(node).__name__} is not allowed in an answer")


def parse_answer(text: str) -> Any:
    """The SymPy value of `text`, or UnsafeAnswer. Never evaluates `text` as Python."""
    if len(text) > MAX_CHARS:
        raise UnsafeAnswer(f"the answer is too long (over {MAX_CHARS} characters)")
    if not _CHARS.fullmatch(text):
        raise UnsafeAnswer("the answer has characters outside plain math")
    try:
        tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise UnsafeAnswer(f"the answer is not an expression: {exc}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise UnsafeAnswer("the expression is too large")
    try:
        value = _eval(tree.body)
    except RecursionError as exc:
        raise UnsafeAnswer("the expression is nested too deeply") from exc
    if value.has(sympy.zoo, sympy.nan):
        raise UnsafeAnswer("the answer is undefined")
    return value
