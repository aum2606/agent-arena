import json
from typing import Any

# Limits on what an attacker may ask the sandbox to run (D-045).
MAX_TESTS = 10
MAX_CHARS = 20_000

# Runs a solution on the inputs and prints only the results. The expected outputs never enter the
# sandbox, so a defender's code cannot read them; the comparison happens outside (answers_match).
_RUNNER = """
import io, json, sys
_out = sys.stdout
sys.stdout = io.StringIO()  # the solution's own prints must not reach the result
_namespace = {"__name__": "solution"}
exec(compile(_SOLUTION, "solution.py", "exec"), _namespace)
_results = [json.loads(json.dumps(_namespace["solve"](*_args))) for _args in _INPUTS]
sys.stdout = _out
print(json.dumps(_results))
"""


def _exact(value: Any) -> None:
    """Floats are out: exact equality of JSON text would fail on 0.1 + 0.2."""
    if isinstance(value, float):
        raise ValueError("floats are not allowed: use integers, strings, booleans, null and lists")
    if isinstance(value, list):
        for item in value:
            _exact(item)
    elif isinstance(value, dict):
        for item in value.values():
            _exact(item)


def _load(text: str, what: str) -> Any:
    if len(text) > MAX_CHARS:
        raise ValueError(f"the {what} are too long (over {MAX_CHARS} characters)")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the {what} are not valid JSON") from exc
    _exact(value)
    return value


def validate(inputs: str, expected: str) -> None:
    """Raise ValueError unless `inputs` is a short JSON list of argument lists and `expected` a
    JSON list with one output per input."""
    tests = _load(inputs, "test inputs")
    if not isinstance(tests, list):
        raise ValueError("the test inputs must be a list of argument lists")
    if not tests:
        raise ValueError("give at least one test")
    if len(tests) > MAX_TESTS:
        raise ValueError(f"give at most {MAX_TESTS} tests")
    if not all(isinstance(args, list) for args in tests):
        raise ValueError("each test must be an argument list")
    outputs = _load(expected, "expected outputs")
    if not isinstance(outputs, list):
        raise ValueError("the expected outputs must be a list")
    if len(outputs) != len(tests):
        raise ValueError("give one expected output per test: the same number of each")


def harness(solution: str, inputs: str) -> str:
    """A snippet that defines `solve` from `solution`, runs it on `inputs` (validated JSON) and
    prints the list of results as JSON."""
    return f"_SOLUTION = {solution!r}\n_INPUTS = {json.loads(inputs)!r}\n{_RUNNER}"
