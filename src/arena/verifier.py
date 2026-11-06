import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import sympy
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

logger = logging.getLogger(__name__)

# convert_xor so "x^2" means a power, as models often write it.
_TRANSFORMATIONS = (*standard_transformations, convert_xor)
# Standard math spellings that SymPy lacks: a defender writing arcsin against a stated asin was
# scored wrong for the same value.
_ALIASES = {"arcsin": sympy.asin, "arccos": sympy.acos, "arctan": sympy.atan}


@dataclass(frozen=True)
class Verification:
    passed: bool
    reason: str


def answers_match(a: str, b: str) -> bool:
    """Exact/symbolic equality. Unparseable text never matches."""
    try:
        diff = sympy.simplify(
            parse_expr(a, local_dict=_ALIASES, transformations=_TRANSFORMATIONS)
            - parse_expr(b, local_dict=_ALIASES, transformations=_TRANSFORMATIONS)
        )
    except Exception as exc:  # parse_expr raises many types on arbitrary model text
        logger.info("answer comparison failed (%r vs %r): %s", a, b, exc)
        return False
    return bool(diff == 0)


def verify_attack(stated_answer: str, snippet: str, timeout_s: float) -> Verification:
    """Run the attacker's snippet; it passes if its output equals the stated answer.

    Not a secure sandbox (see D-002): isolation is a temp dir, minimal env and a timeout.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "snippet.py"
        script.write_text(snippet, encoding="utf-8")
        # SYSTEMROOT is required for Python to start on Windows; nothing else is passed,
        # so API keys in the parent environment stay out of model-written code.
        env = {k: v for k, v in os.environ.items() if k == "SYSTEMROOT"}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return Verification(False, f"timeout after {timeout_s}s")
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        return Verification(False, f"error: {lines[-1] if lines else proc.returncode}")
    output = proc.stdout.strip()
    if not answers_match(output, stated_answer):
        return Verification(
            False, f"mismatch: snippet printed {output!r}, stated {stated_answer!r}"
        )
    return Verification(True, "ok")
