import re

# A problem is shown to the other user's model, so it is checked first (D-049). This is a rule
# filter for instructions aimed at the opponent, not a content moderator: it knows nothing of
# hateful or adult text.

# Of 441 logged problems the 99th percentile is 1,512 characters; two rambled past 4,000.
MAX_PROBLEM_CHARS = 4000

# Zero-width, directional and control characters hide text from a human reading a replay. They are
# listed as numbers so that this file holds no invisible characters itself.
_HIDDEN = (
    (0x00, 0x08),
    (0x0B, 0x0C),
    (0x0E, 0x1F),
    (0x200B, 0x200F),  # zero-width space and joiners, left-to-right and right-to-left marks
    (0x202A, 0x202E),  # bidirectional embeddings and overrides
    (0x2060, 0x2060),  # word joiner
    (0x2066, 0x2069),  # bidirectional isolates
    (0xFEFF, 0xFEFF),  # byte-order mark
)

_AIMED_AT_THE_OPPONENT = (
    (
        "tells the opponent to ignore its instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(instructions?|rules|prompts?|persona|system|above|previous|prior)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "asks the opponent to reveal its instructions or keys",
        re.compile(
            r"\b(reveal|show|print|repeat|leak|disclose|output|tell|give)\b[^.\n]{0,30}"
            r"\b(system prompt|(your|the|its) (instructions|prompt|persona|api key)"
            r"|your (rules|key|secret|password|token))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tries to redefine the opponent's role",
        re.compile(
            r"\byou are now\b|\bnew instructions?\b|\bsystem prompt\b"
            r"|\bdeveloper mode\b|\bjailbreak\b",
            re.IGNORECASE,
        ),
    ),
)


def _has_hidden_characters(text: str) -> bool:
    return any(low <= ord(char) <= high for char in text for low, high in _HIDDEN)


def check_problem(problem: str) -> str | None:
    """Why `problem` is a foul, or None if it may go to the defender."""
    if not problem.strip():
        return "the problem is empty"
    if len(problem) > MAX_PROBLEM_CHARS:
        return f"the problem is over {MAX_PROBLEM_CHARS} characters"
    if _has_hidden_characters(problem):
        return "the problem contains invisible or control characters"
    for reason, pattern in _AIMED_AT_THE_OPPONENT:
        if pattern.search(problem):
            return reason
    return None
