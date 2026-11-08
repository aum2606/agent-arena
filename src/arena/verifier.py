import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from arena.equality import symbolic_equal


@dataclass(frozen=True)
class Verification:
    passed: bool
    reason: str


def _canonical(text: str) -> str:
    # Comparing the text, not the values: in Python 1 == True, in JSON they differ.
    return json.dumps(json.loads(text), sort_keys=True)


def answers_match(a: str, b: str) -> bool:
    """Exact/symbolic equality; two JSON lists (code strike outputs) match if equal as JSON.
    Unparseable text never matches."""
    if a.lstrip().startswith("[") and b.lstrip().startswith("["):
        try:
            return _canonical(a) == _canonical(b)
        except ValueError:
            return False
    return symbolic_equal(a, b)


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
