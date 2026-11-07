import re
from collections import Counter
from collections.abc import Sequence

from arena.codestrike import validate
from arena.models import Attack, Domain, Fighter, Outcome

ANSWER_FORMAT = (
    "Write answers as plain ASCII that SymPy can parse, e.g. 42, 7/3, sqrt(2), x**2 + 1. "
    "Use ** for powers, never ^ or LaTeX. "
    "Euler's number is E and the imaginary unit is I; never write e or i for them."
)

ATTACKER_RULES = f"""You are fighting in Agent Arena. Your opponent loses health when it fails \
a problem you pose.

Pose one math problem with exactly one exact answer (a number or a closed-form expression). \
Make it genuinely hard for an opponent who has no tools and little time: it needs at least \
three distinct steps or ideas, it is not a textbook formula or a well-known closed form, and it \
hides a trap that a careless solver would fall into. A problem a strong solver finishes in one \
or two lines is too easy and will be blocked. But you must be certain of the answer: if your \
snippet's output does not equal your stated answer, or the snippet crashes or runs too long, \
YOU take the damage instead.

Design backwards: start from a structure whose answer you can derive with certainty, then wrap \
it in a multi-step setup with a twist. Your snippet only confirms what you already derived.

To avoid that:
- Keep your working brief, a few lines, and check your result by hand before the tags. Your \
reply is cut off after a fixed length, and a reply cut off before the tags costs you the \
turn. Only the tags at the end of your reply are used.
- Write the Python snippet first, then state exactly what it will print as your answer. Never \
state an answer you have not derived from the snippet's logic.
- The snippet prints only the final value, fully evaluated: a number or a simplified \
expression such as 155 or 5*pi/32. Never print an unevaluated object such as Integral(...) or \
Sum(...); call doit() and simplify().
- The snippet must finish quickly. Counting, searching or simulating over up to a few million \
cases is fine; keep symbolic work simple.
- Use only the standard library or sympy.

{ANSWER_FORMAT}"""

DEFENDER_RULES = f"""You are fighting in Agent Arena. Your opponent has posed a math problem. \
If your final answer is wrong you lose health. You have limited time and tokens, so keep your \
reasoning short.

{ANSWER_FORMAT}"""

CODE_ATTACKER_RULES = """You are fighting in Agent Arena. Your opponent loses health when its \
code fails tests that you hide from it.

Pose one programming problem: a Python function `solve` that takes plain arguments and returns a \
value, solvable with the standard library only. Make it genuinely hard for an opponent who has no \
tools and little time: it needs at least three distinct steps or ideas, and it hides a trap, such \
as an edge case that a careless solver would miss. State the exact signature of `solve`, the types \
of its arguments and result, and any limits in the problem text. A problem a strong solver \
finishes in a few lines is too easy and will be blocked. But you must be certain of your tests: \
your reference solution is run on your test inputs, and if its output does not equal the expected \
outputs you state, or it crashes or runs too long, YOU take the damage instead.

To avoid that:
- Keep your working brief, a few lines, and check your tests by hand before the tags. Your reply \
is cut off after a fixed length, and a reply cut off before the tags costs you the turn.
- Give 4 to 10 tests, with edge cases: empty and extreme inputs, duplicates, ties.
- Arguments and results are JSON: integers, strings, booleans, null, lists and objects with \
string keys. Never floats.
- The reference solution must be deterministic and fast. It must not read input or use the \
network; anything it prints is ignored.
- `<tests>` is a JSON list with one inner list of positional arguments per test. `<answer>` is a \
JSON list with one expected output per test, in the same order, written as `json.dumps` would \
print your solution's results."""

CODE_DEFENDER_RULES = """You are fighting in Agent Arena. Your opponent has posed a programming \
problem. Write a Python function `solve` for it, using the standard library only. It is run on \
hidden tests; if any output is wrong, or it crashes or runs too long, you lose health. Return \
plain JSON values (integers, strings, booleans, None, lists, dicts), never floats. You have \
limited time and tokens, so keep your reasoning short."""

HISTORY_WINDOW = 10  # how many of an attacker's latest problems its feedback summarises

# One is picked at random per turn: without it, deterministic models repeat one easy problem.
TOPICS = (
    "number theory",
    "combinatorics",
    "algebra and polynomials",
    "probability",
    "series and sums",
    "calculus (limits, derivatives, integrals)",
    "geometry and trigonometry",
    "linear algebra",
    "recurrences and sequences",
    "modular arithmetic",
)

# One is picked at random for a code turn, like TOPICS for math.
CODE_TOPICS = (
    "strings",
    "arrays and sorting",
    "dynamic programming",
    "graphs and grids",
    "parsing and formatting",
    "recursion and backtracking",
    "number theory",
    "simulation",
)

ATTACK_REQUEST = """Reply in exactly this format:
<problem>the problem statement</problem>
<code>python snippet that prints the answer</code>
<answer>your answer, written exactly as the snippet prints it</answer>"""

CODE_ATTACK_REQUEST = """Reply in exactly this format:
<problem>the problem statement, including the exact signature of solve</problem>
<code>reference solution (Python) that defines solve</code>
<tests>JSON list of argument lists, one per test</tests>
<answer>JSON list of expected outputs, one per test</answer>"""

DEFENSE_REQUEST = "Reply with your final answer inside <answer></answer> tags."
CODE_DEFENSE_REQUEST = "Reply with your function inside <code></code> tags."

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


class ParseError(Exception):
    pass


def attack_prompts(
    fighter: Fighter,
    topic: str,
    used_problems: list[str],
    recent_outcomes: Sequence[Outcome] = (),
    domain: Domain = "math",
) -> tuple[str, str]:
    """(system, user) messages asking the fighter to attack with a problem on `topic`.

    `recent_outcomes` are how its own earlier problems ended, oldest first; the summary nudges
    its difficulty toward the point where about a third of its problems land (D-022, D-023).
    """
    parts = [f"Topic for this turn: {topic}. Pose your problem in that area."]
    if used_problems:
        listed = "\n".join(f"- {problem}" for problem in used_problems)
        parts.append(
            f"Problems already posed in this match:\n{listed}\n"
            "Do not repeat them or pose close variants."
        )
    if recent_outcomes:
        window = recent_outcomes[-HISTORY_WINDOW:]
        counts = Counter(window)
        parts.append(
            f"How your last {len(window)} problems fared - "
            f"blocked by your opponent (too easy): {counts['block']}; "
            f"failed your own check (too hard): {counts['backfire']}; "
            f"hit your opponent: {counts['hit']}. "
            "Aim for about a third of your problems to hit your opponent: if most were blocked, "
            "make the next one clearly harder; if many failed your own check, make it a little "
            "easier."
        )
    code = domain == "code"
    parts.append(CODE_ATTACK_REQUEST if code else ATTACK_REQUEST)
    rules = CODE_ATTACKER_RULES if code else ATTACKER_RULES
    return f"{fighter.persona}\n\n{rules}", "\n\n".join(parts)


def _with_note(user: str, note: str) -> str:
    # The reply format stays last, as in the first prompt.
    request = CODE_ATTACK_REQUEST if user.endswith(CODE_ATTACK_REQUEST) else ATTACK_REQUEST
    return f"{user.removesuffix(request)}{note}\n\n{request}"


def correction_prompt(user: str, attack: Attack, reason: str) -> str:
    """`user` (an attack prompt) plus how `attack` failed its check, for the one retry (D-025)."""
    tests = f"<tests>{attack.inputs}</tests>\n" if attack.domain == "code" else ""
    note = (
        "Your previous attempt failed the check that runs your snippet:\n"
        f"<problem>{attack.problem}</problem>\n"
        f"<code>{attack.snippet}</code>\n"
        f"{tests}"
        f"<answer>{attack.answer}</answer>\n"
        f"Result: {reason}\n"
        "Decide whether your stated answer or your code is wrong and fix that one. Keep the "
        "problem unless it is itself flawed, and make sure the answer is for the problem as "
        "written. This is your only retry: if the corrected attempt fails too, you take the "
        "damage."
    )
    return _with_note(user, note)


def unparsed_prompt(user: str, truncated: bool) -> str:
    """`user` plus why the first reply was unusable, for the one retry (D-040)."""
    why = (
        "was cut off before it reached the tags"
        if truncated
        else "could not be read: the problem, code and answer tags were missing or empty"
    )
    note = (
        f"Your previous reply {why}. Keep your working brief, a few lines, and write the three "
        "tags as soon as you have the problem, the code and the answer. This is your only "
        "retry: if the next reply fails too, you take the damage."
    )
    return _with_note(user, note)


def defense_prompts(fighter: Fighter, problem: str, domain: Domain = "math") -> tuple[str, str]:
    """(system, user) messages asking the fighter to solve `problem`."""
    if domain == "code":
        return f"{fighter.persona}\n\n{CODE_DEFENDER_RULES}", f"{problem}\n\n{CODE_DEFENSE_REQUEST}"
    return f"{fighter.persona}\n\n{DEFENDER_RULES}", f"{problem}\n\n{DEFENSE_REQUEST}"


def _tag(text: str, name: str) -> str:
    # Last match wins: models sometimes draft an answer, then correct it.
    matches: list[str] = re.findall(rf"<{name}>(.*?)</{name}>", text, re.DOTALL)
    if not matches or not matches[-1].strip():
        raise ParseError(f"missing or empty <{name}>")
    return matches[-1].strip()


def _code(text: str) -> str:
    snippet = _tag(text, "code")
    fenced = _FENCE.search(snippet)
    if fenced:
        return fenced.group(1).strip()
    # Models copy the "python" of "python snippet that prints the answer" from the format.
    label, _, rest = snippet.partition("\n")
    return rest.strip() if label.strip().lower() == "python" and rest.strip() else snippet


def parse_attack(text: str, domain: Domain = "math") -> Attack:
    snippet = _code(text)
    problem, answer = _tag(text, "problem"), _tag(text, "answer")
    if domain == "math":
        return Attack(problem, answer, snippet)
    inputs = _tag(text, "tests")
    try:
        validate(inputs, answer)
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
    return Attack(problem, answer, snippet, "code", inputs)


def parse_defense(text: str) -> str:
    return _tag(text, "answer")


def parse_code_defense(text: str) -> str:
    return _code(text)
