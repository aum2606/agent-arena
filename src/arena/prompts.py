import re

from arena.models import Attack, Fighter

ANSWER_FORMAT = (
    "Write answers as plain ASCII that SymPy can parse, e.g. 42, 7/3, sqrt(2), x**2 + 1. "
    "Use ** for powers, never ^ or LaTeX."
)

ATTACKER_RULES = f"""You are fighting in Agent Arena. Your opponent loses health when it fails \
a problem you pose.

Pose one math problem with exactly one exact answer (a number or a closed-form expression). \
Make it hard for an opponent who has no tools and little time, but it must be correct: you must \
also give your answer and a short Python snippet that prints that answer and nothing else. \
Use only the standard library or sympy. If the snippet's output does not equal your stated \
answer, or it crashes or runs for more than a few seconds, YOU take the damage instead.

{ANSWER_FORMAT}"""

DEFENDER_RULES = f"""You are fighting in Agent Arena. Your opponent has posed a math problem. \
If your final answer is wrong you lose health. You have limited time and tokens, so keep your \
reasoning short.

{ANSWER_FORMAT}"""

ATTACK_REQUEST = """Reply in exactly this format:
<problem>the problem statement</problem>
<answer>your answer</answer>
<code>python snippet that prints the answer</code>"""

DEFENSE_REQUEST = "Reply with your final answer inside <answer></answer> tags."

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


class ParseError(Exception):
    pass


def attack_prompts(fighter: Fighter) -> tuple[str, str]:
    """(system, user) messages asking the fighter to attack."""
    return f"{fighter.persona}\n\n{ATTACKER_RULES}", ATTACK_REQUEST


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
