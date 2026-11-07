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


@dataclass(frozen=True)
class Run:
    """How a snippet ended, wherever it ran (local subprocess or sandbox)."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def judge(run: Run, stated_answer: str, timeout_s: float) -> Verification:
    """A snippet passes if it finished and its output equals the stated answer."""
    if run.timed_out:
        return Verification(False, f"timeout after {timeout_s}s")
    if run.returncode != 0:
        lines = run.stderr.strip().splitlines()
        return Verification(False, f"error: {lines[-1] if lines else run.returncode}")
    output = run.stdout.strip()
    if not answers_match(output, stated_answer):
        return Verification(
            False, f"mismatch: snippet printed {output!r}, stated {stated_answer!r}"
        )
    return Verification(True, "ok")


def run_local(snippet: str, timeout_s: float) -> Run:
    """Not a secure sandbox (see D-002): isolation is a temp dir, minimal env and a timeout. The
    web worker uses `sandbox.run_sandboxed` instead (D-044)."""
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
            return Run(-1, "", "", timed_out=True)
    return Run(proc.returncode, proc.stdout, proc.stderr)


def verify_attack(stated_answer: str, snippet: str, timeout_s: float) -> Verification:
    """Run the attacker's snippet locally; it passes if its output equals the stated answer."""
    return judge(run_local(snippet, timeout_s), stated_answer, timeout_s)
