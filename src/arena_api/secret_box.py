import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from arena.config import ConfigError


def _fernet() -> MultiFernet:
    """The current secret encrypts; it and any old ones listed in KEY_ENCRYPTION_OLD_SECRETS (a
    comma-separated list, for a rotation in progress; D-078) decrypt."""
    secret = os.environ.get("KEY_ENCRYPTION_SECRET")
    if not secret:
        raise ConfigError("KEY_ENCRYPTION_SECRET is not set (see .env.example)")
    try:
        current = Fernet(secret)
    except ValueError as exc:
        raise ConfigError(
            "KEY_ENCRYPTION_SECRET is not a valid key; make one with Fernet.generate_key() "
            "from the cryptography package"
        ) from exc
    listed = os.environ.get("KEY_ENCRYPTION_OLD_SECRETS", "")
    old = [s.strip() for s in listed.split(",") if s.strip()]
    try:
        return MultiFernet([current, *(Fernet(s) for s in old)])
    except ValueError as exc:
        raise ConfigError("KEY_ENCRYPTION_OLD_SECRETS has a value that is not a valid key") from exc


def check_secret() -> None:
    """Raise ConfigError if the secret is missing or not a valid key. The API and the worker call it
    on startup, so a deploy without it fails at once, not on the first user's key."""
    _fernet()


def encrypt(plain: str) -> str:
    """Encrypt an API key for storage with the server's secret."""
    return _fernet().encrypt(plain.encode()).decode()


def reencrypt(stored: str) -> str:
    """The same key, stored under the current secret (for a rotation; D-078)."""
    try:
        return _fernet().rotate(stored.encode()).decode()
    except InvalidToken as exc:
        raise ConfigError(
            "a stored API key could not be decrypted: list its secret in KEY_ENCRYPTION_OLD_SECRETS"
        ) from exc


def decrypt(stored: str) -> str:
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken as exc:
        raise ConfigError(
            "a stored API key could not be decrypted (wrong or changed KEY_ENCRYPTION_SECRET?)"
        ) from exc
