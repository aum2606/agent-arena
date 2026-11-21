"""Stored API keys, sealed so that only the worker can open them (D-082).

The API process seals a key to a public key (`KEY_PUBLIC_KEY`) and cannot open what it stored; only
the worker holds the private key (`KEY_PRIVATE_KEY`). The seal is an X25519 sealed box: an ephemeral
key agrees a secret with the public key, HKDF turns it into a key, ChaCha20-Poly1305 encrypts. A
stored value is `v2:` plus the URL-safe base64 of the ephemeral public key, a nonce and the
ciphertext.

Local development keeps the older mode (D-034, D-078): with no public key set, a key is encrypted
with the symmetric `KEY_ENCRYPTION_SECRET` (a Fernet key), and values stored that way still open, so
an install can move over (`python -m arena_api.rotate_keys`).
"""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from arena.config import ConfigError

PREFIX = "v2:"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_INFO = b"arena-api-key-v2"


def _raw(public: X25519PublicKey) -> bytes:
    return public.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _decode_key(name: str, text: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ConfigError(f"{name} is not a valid key (see .env.example)") from exc
    if len(raw) != _KEY_BYTES:
        raise ConfigError(f"{name} is not a valid key (see .env.example)")
    return raw


def encode_key(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _public_key() -> X25519PublicKey | None:
    text = os.environ.get("KEY_PUBLIC_KEY")
    return X25519PublicKey.from_public_bytes(_decode_key("KEY_PUBLIC_KEY", text)) if text else None


def _private_keys() -> list[X25519PrivateKey]:
    """The current private key first, then listed old ones (while a keypair is being replaced)."""
    names = [("KEY_PRIVATE_KEY", os.environ.get("KEY_PRIVATE_KEY", ""))]
    old = os.environ.get("KEY_OLD_PRIVATE_KEYS", "")
    names += [("KEY_OLD_PRIVATE_KEYS", part.strip()) for part in old.split(",") if part.strip()]
    return [
        X25519PrivateKey.from_private_bytes(_decode_key(name, text)) for name, text in names if text
    ]


def _fernet() -> MultiFernet | None:
    """The symmetric secret: the current one encrypts, it and any retired ones in
    KEY_ENCRYPTION_OLD_SECRETS (comma-separated; D-078) decrypt. None when it is not set."""
    secret = os.environ.get("KEY_ENCRYPTION_SECRET")
    if not secret:
        return None
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


def _seal(plain: bytes, public: X25519PublicKey) -> bytes:
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(public)
    ephemeral_raw = _raw(ephemeral.public_key())
    key = HKDF(hashes.SHA256(), _KEY_BYTES, salt=ephemeral_raw + _raw(public), info=_INFO).derive(
        shared
    )
    nonce = os.urandom(_NONCE_BYTES)
    return ephemeral_raw + nonce + ChaCha20Poly1305(key).encrypt(nonce, plain, ephemeral_raw)


def _open(sealed: bytes, private: X25519PrivateKey) -> bytes:
    ephemeral_raw = sealed[:_KEY_BYTES]
    nonce = sealed[_KEY_BYTES : _KEY_BYTES + _NONCE_BYTES]
    shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_raw))
    salt = ephemeral_raw + _raw(private.public_key())
    key = HKDF(hashes.SHA256(), _KEY_BYTES, salt=salt, info=_INFO).derive(shared)
    return ChaCha20Poly1305(key).decrypt(nonce, sealed[_KEY_BYTES + _NONCE_BYTES :], ephemeral_raw)


_CANNOT_STORE = (
    "KEY_PUBLIC_KEY is not set (or, for local development, KEY_ENCRYPTION_SECRET): see .env.example"
)
_CANNOT_OPEN = (
    "KEY_PRIVATE_KEY is not set (or, for local development, KEY_ENCRYPTION_SECRET): "
    "see .env.example"
)


def check_secret() -> None:
    """For the API: raise ConfigError unless it can store a key, with a public key or, in local
    development, the symmetric secret. A deploy without either fails at start-up, not on the first
    user's key."""
    if _public_key() is None and _fernet() is None:
        raise ConfigError(_CANNOT_STORE)


def check_worker_keys() -> None:
    """For the worker: raise ConfigError unless it can open stored keys (KEY_PRIVATE_KEY, or the
    symmetric secret for keys stored the older way)."""
    if not _private_keys() and _fernet() is None:
        raise ConfigError(_CANNOT_OPEN)


def encrypt(plain: str) -> str:
    """Store an API key: sealed to the public key, or with the symmetric secret in local mode."""
    public = _public_key()
    if public is not None:
        return PREFIX + base64.urlsafe_b64encode(_seal(plain.encode(), public)).decode()
    fernet = _fernet()
    if fernet is None:
        raise ConfigError(_CANNOT_STORE)
    return fernet.encrypt(plain.encode()).decode()


def decrypt(stored: str) -> str:
    """The key behind a stored value; only a process with the private key (or the symmetric secret
    for older values) can do this."""
    cannot = ConfigError(
        "a stored API key could not be decrypted (wrong or changed key or secret?)"
    )
    if stored.startswith(PREFIX):
        privates = _private_keys()
        if not privates:
            raise ConfigError("KEY_PRIVATE_KEY is not set: this process cannot open stored keys")
        try:
            sealed = base64.urlsafe_b64decode(stored[len(PREFIX) :])
        except (binascii.Error, ValueError):
            raise cannot from None
        if len(sealed) < _KEY_BYTES + _NONCE_BYTES + 16:
            raise cannot
        for private in privates:
            try:
                return _open(sealed, private).decode()
            except (InvalidTag, ValueError):
                continue
        raise cannot
    fernet = _fernet()
    if fernet is None:
        raise ConfigError("KEY_ENCRYPTION_SECRET is not set: this process cannot open stored keys")
    try:
        return fernet.decrypt(stored.encode()).decode()
    except InvalidToken:
        raise cannot from None


def reencrypt(stored: str) -> str:
    """The same key, stored under the current public key (or the current symmetric secret in local
    mode): for moving to the sealed format or to a new keypair. Needs everything that opens it."""
    return encrypt(decrypt(stored))
