import os

from cryptography.fernet import Fernet, InvalidToken

from arena.config import ConfigError


def _fernet() -> Fernet:
    secret = os.environ.get("KEY_ENCRYPTION_SECRET")
    if not secret:
        raise ConfigError("KEY_ENCRYPTION_SECRET is not set (see .env.example)")
    try:
        return Fernet(secret)
    except ValueError as exc:
        raise ConfigError(
            "KEY_ENCRYPTION_SECRET is not a valid key; make one with Fernet.generate_key() "
            "from the cryptography package"
        ) from exc


def encrypt(plain: str) -> str:
    """Encrypt an API key for storage with the server's secret."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(stored: str) -> str:
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken as exc:
        raise ConfigError(
            "a stored API key could not be decrypted (wrong or changed KEY_ENCRYPTION_SECRET?)"
        ) from exc
