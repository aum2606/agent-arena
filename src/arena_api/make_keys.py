"""Make the keypair that stored API keys are sealed with: `python -m arena_api.make_keys`.

Put KEY_PUBLIC_KEY in the API's environment and KEY_PRIVATE_KEY in the worker's only, and back the
private key up somewhere else: without it every stored key is unreadable (D-082).
"""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from arena_api.secret_box import encode_key


def generate() -> tuple[str, str]:
    """(public, private) as they are written in the environment."""
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return encode_key(raw_public), encode_key(raw_private)


def main() -> None:
    public, private = generate()
    print(f"KEY_PUBLIC_KEY={public}")
    print(f"KEY_PRIVATE_KEY={private}")


if __name__ == "__main__":
    main()
