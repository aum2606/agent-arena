import re
from collections import Counter
from collections.abc import Sequence

from arena.models import Attack, Fighter, Outcome

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

ATTACK_REQUEST = """Reply in exactly this format:
<problem>the problem statement</problem>
<code>python snippet that prints the answer</code>
<answer>your answer, written exactly as the snippet prints it</answer>"""

DEFENSE_REQUEST = "Reply with your final answer inside <answer></answer> tags."

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


class ParseError(Exception):
    pass


def attack_prompts(
    fighter: Fighter,
    topic: str,
    used_problems: list[str],
    recent_outcomes: Sequence[Outcome] = (),
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
    parts.append(ATTACK_REQUEST)
    return f"{fighter.persona}\n\n{ATTACKER_RULES}", "\n\n".join(parts)


def _with_note(user: str, note: str) -> str:
    # The reply format stays last, as in the first prompt.
    return f"{user.removesuffix(ATTACK_REQUEST)}{note}\n\n{ATTACK_REQUEST}"


def correction_prompt(user: str, attack: Attack, reason: str) -> str:
    """`user` (an attack prompt) plus how `attack` failed its check, for the one retry (D-025)."""
    note = (
        "Your previous attempt failed the check that runs your snippet:\n"
        f"<problem>{attack.problem}</problem>\n"
        f"<code>{attack.snippet}</code>\n"
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
