import re

from arena.models import Attack, Fighter

ANSWER_FORMAT = (
    "Write answers as plain ASCII that SymPy can parse, e.g. 42, 7/3, sqrt(2), x**2 + 1. "
    "Use ** for powers, never ^ or LaTeX. "
    "Euler's number is E and the imaginary unit is I; never write e or i for them."
)

ATTACKER_RULES = f"""You are fighting in Agent Arena. Your opponent loses health when it fails \
a problem you pose.

Pose one math problem with exactly one exact answer (a number or a closed-form expression). \
Make it hard for an opponent who has no tools and little time, but you must be certain of the \
answer: if your snippet's output does not equal your stated answer, or the snippet crashes or \
runs too long, YOU take the damage instead.

To avoid that:
- Work the problem out step by step before the tags and check your result by hand. Only the \
tags at the end of your reply are used.
- Write the Python snippet first, then state exactly what it will print as your answer. Never \
state an answer you have not derived from the snippet's logic.
- The snippet prints only the final value, fully evaluated: a number or a simplified \
expression such as 155 or 5*pi/32. Never print an unevaluated object such as Integral(...) or \
Sum(...); call doit() and simplify().
- Prefer problems that plain Python or simple sympy settle quickly: counting, sums, modular \
arithmetic, number theory, and integrals or series with exact closed forms.
- Use only the standard library or sympy.

{ANSWER_FORMAT}"""

DEFENDER_RULES = f"""You are fighting in Agent Arena. Your opponent has posed a math problem. \
If your final answer is wrong you lose health. You have limited time and tokens, so keep your \
reasoning short.

{ANSWER_FORMAT}"""

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

ATTACK_REQUEST = """Reply in exactly this format:
<problem>the problem statement</problem>
<code>python snippet that prints the answer</code>
<answer>your answer, written exactly as the snippet prints it</answer>"""

DEFENSE_REQUEST = "Reply with your final answer inside <answer></answer> tags."

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


class ParseError(Exception):
    pass


def attack_prompts(fighter: Fighter, topic: str, used_problems: list[str]) -> tuple[str, str]:
    """(system, user) messages asking the fighter to attack with a problem on `topic`."""
    parts = [f"Topic for this turn: {topic}. Pose your problem in that area."]
    if used_problems:
        listed = "\n".join(f"- {problem}" for problem in used_problems)
        parts.append(
            f"Problems already posed in this match:\n{listed}\n"
            "Do not repeat them or pose close variants."
        )
    parts.append(ATTACK_REQUEST)
    return f"{fighter.persona}\n\n{ATTACKER_RULES}", "\n\n".join(parts)


def defense_prompts(fighter: Fighter, problem: str) -> tuple[str, str]:
    """(system, user) messages asking the fighter to solve `problem`."""
    return f"{fighter.persona}\n\n{DEFENDER_RULES}", f"{problem}\n\n{DEFENSE_REQUEST}"


def _tag(text: str, name: str) -> str:
    # Last match wins: models sometimes draft an answer, then correct it.
    matches: list[str] = re.findall(rf"<{name}>(.*?)</{name}>", text, re.DOTALL)
    if not matches or not matches[-1].strip():
        raise ParseError(f"missing or empty <{name}>")
    return matches[-1].strip()


def parse_attack(text: str) -> Attack:
    snippet = _tag(text, "code")
    fenced = _FENCE.search(snippet)
    if fenced:
        snippet = fenced.group(1).strip()
    return Attack(_tag(text, "problem"), _tag(text, "answer"), snippet)


def parse_defense(text: str) -> str:
    return _tag(text, "answer")
