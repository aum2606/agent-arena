"""A record of security-relevant events, one line each, for whoever investigates (D-081).

Lines go to the `arena.security` logger as `security event=... key=value ...`. Values are cut,
stripped of control characters and quoted when they hold anything but plain characters, so nothing
a visitor sends can start a line or a field of its own. Never pass a secret, a token or a key.
"""

import json
import logging
import re

logger = logging.getLogger("arena.security")

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_PLAIN = re.compile(r"[A-Za-z0-9_./:@-]+")
MAX_VALUE = 100


def _value(value: object) -> str:
    text = _CONTROL.sub(" ", str(value))[:MAX_VALUE]
    return text if _PLAIN.fullmatch(text) else json.dumps(text)


def record(event: str, **fields: object) -> None:
    parts = [f"event={event}", *(f"{key}={_value(value)}" for key, value in fields.items())]
    logger.info("security %s", " ".join(parts))
