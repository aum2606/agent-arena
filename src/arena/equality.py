"""Compare two answers' values with a time limit.

Reading an answer is bounded (`safe_expr`), but `sympy.simplify` is not: a 32-character product of
three powers ran for over 25 seconds, and the worker plays one match at a time. The comparison
therefore runs in one long-lived helper process that is killed and replaced when it takes too long
(D-052).
"""

import logging
import multiprocessing
import threading
from multiprocessing.process import BaseProcess
from typing import Any

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


# Connections are typed Any: on Windows a Pipe is a PipeConnection, which typeshed does not make a
# subclass of Connection.
def _serve(connection: Any) -> None:
    """The helper's loop: compare each pair it is sent."""
    connection.send("ready")
    while True:
        try:
            a, b = connection.recv()
        except EOFError:  # the parent is gone
            return
        connection.send(_equal_now(a, b))


class _Helper:
    def __init__(self) -> None:
        self._lock = threading.Lock()  # one comparison at a time: there is one helper
        self._process: BaseProcess | None = None
        self._connection: Any = None

    def _start(self) -> Any:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_serve, args=(child,), daemon=True)
        process.start()
        child.close()
        if not parent.poll(START_TIMEOUT_S) or parent.recv() != "ready":
            process.kill()
            raise ConfigError("the answer checker did not start")
        self._process, self._connection = process, parent
        return parent

    def _stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.join()
        if self._connection is not None:
            self._connection.close()
        self._process = self._connection = None

    def equal(self, a: str, b: str) -> tuple[bool, str]:
        with self._lock:
            alive = self._process is not None and self._process.is_alive()
            connection = self._connection if alive and self._connection else self._start()
            connection.send((a, b))
            if connection.poll(TIMEOUT_S):
                result: tuple[bool, str] = connection.recv()
                return result
            self._stop()  # SymPy cannot be interrupted; the next call starts a fresh helper
            return False, f"the comparison took over {TIMEOUT_S} s"


_helper = _Helper()


def symbolic_equal(a: str, b: str) -> bool:
    """True if the answers have the same value; unreadable, refused or too slow text is False."""
    equal, why = _helper.equal(a, b)
    if why:
        logger.info("answer comparison failed (%r vs %r): %s", a, b, why)
    return equal
