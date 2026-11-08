"""Compare two answers' values with a time limit.

Reading an answer is bounded (`safe_expr`), but `sympy.simplify` is not: a 32-character product of
three powers ran for over 25 seconds, and the worker plays one match at a time. The comparison
therefore runs in one long-lived helper process that is killed and replaced when it takes too long
(D-052). The helper is a plain `python -m arena.equality` talking JSON lines over its pipes:
`multiprocessing`'s spawn method re-runs the caller's main script in the child, which breaks scripts
without a main guard (D-053).
"""

import atexit
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import sympy

from arena.config import ConfigError
from arena.safe_expr import parse_answer

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0  # a slow-looking but honest answer took about 2 s; longer is treated as a non-match
START_TIMEOUT_S = 60.0  # the helper imports SymPy before it can answer


def _equal_now(a: str, b: str) -> tuple[bool, str]:
    """(equal, why not): text from a model is refused, malformed, or SymPy fails on it."""
    try:
        return bool(sympy.simplify(parse_answer(a) - parse_answer(b)) == 0), ""
    except Exception as exc:  # parse_answer and SymPy raise many types on arbitrary text
        return False, str(exc)


def _serve() -> None:
    """The helper's loop: one JSON pair per input line, one JSON result per output line."""
    protocol = sys.stdout
    sys.stdout = sys.stderr  # nothing a comparison prints may be mistaken for a result
    protocol.write("ready\n")
    protocol.flush()
    for line in sys.stdin:
        a, b = json.loads(line)
        protocol.write(json.dumps(_equal_now(a, b)) + "\n")  # ASCII only: no pipe encoding issues
        protocol.flush()


def _helper_environment() -> dict[str, str]:
    """What Python needs to start, and nothing else: no provider keys, no database URL."""
    environment = {key: value for key, value in os.environ.items() if key == "SYSTEMROOT"}
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    return environment


def _read_lines(process: "subprocess.Popen[str]", lines: "queue.Queue[str | None]") -> None:
    assert process.stdout is not None
    for line in process.stdout:
        lines.put(line)
    lines.put(None)  # the helper exited


class _Helper:
    def __init__(self) -> None:
        self._lock = threading.Lock()  # one comparison at a time: there is one helper
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()

    def _start(self) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-m", "arena.equality"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="ascii",
            env=_helper_environment(),
        )
        lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=_read_lines, args=(process, lines), daemon=True).start()
        try:
            ready = lines.get(timeout=START_TIMEOUT_S)
        except queue.Empty:
            ready = None
        if ready != "ready\n":
            process.kill()
            raise ConfigError("the answer checker did not start (run `python -m arena.equality`)")
        self._process, self._lines = process, lines
        return process

    def stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.wait()
            for pipe in (self._process.stdin, self._process.stdout):
                if pipe is not None:
                    pipe.close()
        self._process = None

    def equal(self, a: str, b: str) -> tuple[bool, str]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                process = self._start()
            assert process.stdin is not None
            try:
                process.stdin.write(json.dumps([a, b]) + "\n")
                process.stdin.flush()
                line = self._lines.get(timeout=TIMEOUT_S)
            except queue.Empty:
                self.stop()  # SymPy cannot be interrupted; the next call starts a fresh helper
                return False, f"the comparison took over {TIMEOUT_S} s"
            except OSError:
                line = None
            if line is None:
                self.stop()
                return False, "the answer checker stopped"
            equal, why = json.loads(line)
            return bool(equal), str(why)


_helper = _Helper()
atexit.register(_helper.stop)


def symbolic_equal(a: str, b: str) -> bool:
    """True if the answers have the same value; unreadable, refused or too slow text is False."""
    equal, why = _helper.equal(a, b)
    if why:
        logger.info("answer comparison failed (%r vs %r): %s", a, b, why)
    return equal


if __name__ == "__main__":
    _serve()
