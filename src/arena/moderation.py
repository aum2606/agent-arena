import re
import unicodedata
from collections.abc import Sequence

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
    (0x7F, 0x9F),  # delete and the C1 controls
    (0xAD, 0xAD),  # soft hyphen: invisible, splits a word for the filter but not for a model
    (0x61C, 0x61C),  # Arabic letter mark
    (0x115F, 0x1160),  # Hangul fillers
    (0x17B4, 0x17B5),  # Khmer inherent vowels
    (0x180B, 0x180E),  # Mongolian selectors and separator
    (0x2061, 0x2064),  # invisible function application, times, separator, plus
    (0x206A, 0x206F),  # deprecated format characters
    (0x3164, 0x3164),  # Hangul filler
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFFA0, 0xFFA0),  # half-width Hangul filler
    (0xFFF9, 0xFFFB),  # interlinear annotation
    (0xE0000, 0xE007F),  # "tag" characters: invisible to people, readable by models
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
    (
        "tells the opponent what to answer",
        re.compile(
            r"\bpretend\b[^.\n]{0,20}\byou\b"
            r"|\byou must (answer|respond|reply|output|say|print)\b"
            r"|\b(answer|respond|reply) (only )?with\b"
            r"|\bfrom now on,? (every|all|always|you|your|answer|reply|respond|say|output|print)\b"
            r"|\b(do not|don't|never) (solve|answer)\b"
            r"|\bdisregard everything\b",
            re.IGNORECASE,
        ),
    ),
)

# Letters from other alphabets that look like Latin ones, so a Cyrillic "i" in "ignore" is not a
# way round the rules above. Code points, because the letters look exactly like ASCII ones in this
# file. Not a full confusables table: the common Cyrillic and Greek ones.
_LOOK_ALIKES = str.maketrans(
    {
        # Cyrillic, lower case: a e o p c x y i j s
        0x430: "a",
        0x435: "e",
        0x43E: "o",
        0x440: "p",
        0x441: "c",
        0x445: "x",
        0x443: "y",
        0x456: "i",
        0x458: "j",
        0x455: "s",
        # Cyrillic, upper case
        0x410: "A",
        0x412: "B",
        0x415: "E",
        0x41A: "K",
        0x41C: "M",
        0x41D: "H",
        0x41E: "O",
        0x420: "P",
        0x421: "C",
        0x422: "T",
        0x425: "X",
        0x406: "I",
        0x408: "J",
        0x405: "S",
        # Greek
        0x3BF: "o",
        0x3BD: "v",
        0x3B9: "i",
        0x39F: "O",
        0x391: "A",
        0x392: "B",
        0x395: "E",
        0x396: "Z",
        0x397: "H",
        0x399: "I",
        0x39A: "K",
        0x39C: "M",
        0x39D: "N",
        0x3A1: "P",
        0x3A4: "T",
        0x3A5: "Y",
        0x3A7: "X",
    }
)


def _is_hidden(char: str) -> bool:
    return any(low <= ord(char) <= high for low, high in _HIDDEN)


def has_hidden_characters(text: str) -> bool:
    return any(_is_hidden(char) for char in text)


def strip_hidden(text: str) -> str:
    """`text` without the characters a person reading a replay cannot see."""
    return "".join(char for char in text if not _is_hidden(char))


def _plain(text: str) -> str:
    """How a model reads `text`: full-width and look-alike letters as plain ones, nothing hidden."""
    return unicodedata.normalize("NFKC", strip_hidden(text)).translate(_LOOK_ALIKES)


def check_text(text: str, blocked_terms: Sequence[str]) -> str | None:
    """Why `text` holds a term the deployer blocked (config `blocked_terms`), or None. A term is a
    whole word or phrase in any case; the reason never repeats it (D-080)."""
    if not blocked_terms:
        return None
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, blocked_terms)) + r")\b", re.IGNORECASE)
    return "contains a term this site does not allow" if pattern.search(_plain(text)) else None


def check_problem(problem: str, blocked_terms: Sequence[str] = ()) -> str | None:
    """Why `problem` is a foul, or None if it may go to the defender."""
    if not problem.strip():
        return "the problem is empty"
    if len(problem) > MAX_PROBLEM_CHARS:
        return f"the problem is over {MAX_PROBLEM_CHARS} characters"
    if has_hidden_characters(problem):
        return "the problem contains invisible or control characters"
    plain = _plain(problem)
    for reason, pattern in _AIMED_AT_THE_OPPONENT:
        if pattern.search(plain):
            return reason
    blocked = check_text(problem, blocked_terms)
    return f"the problem {blocked}" if blocked else None
