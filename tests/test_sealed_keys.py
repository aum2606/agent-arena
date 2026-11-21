"""Stored API keys are sealed to a public key, so only the worker can open them (D-082)."""

from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from helpers import SignIn, StubQueue, make_fighter

from arena.config import ConfigError
from arena_api import fighters, make_keys, rotate_keys
from arena_api.secret_box import (
    check_secret,
    check_worker_keys,
    decrypt,
    encrypt,
    reencrypt,
)

PLAIN = "gsk_provider_key_0123456789"
type Pair = tuple[str, str]


def new_pair() -> Pair:
    """(public, private) as they appear in the environment."""
    return make_keys.generate()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "KEY_ENCRYPTION_SECRET",
        "KEY_ENCRYPTION_OLD_SECRETS",
        "KEY_PUBLIC_KEY",
        "KEY_PRIVATE_KEY",
        "KEY_OLD_PRIVATE_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pair(monkeypatch: pytest.MonkeyPatch) -> Pair:
    public, private = new_pair()
    monkeypatch.setenv("KEY_PUBLIC_KEY", public)
    monkeypatch.setenv("KEY_PRIVATE_KEY", private)
    return public, private


def api_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the API process has: the public key and nothing that opens a stored key."""
    monkeypatch.delenv("KEY_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("KEY_ENCRYPTION_SECRET", raising=False)


def test_a_key_is_sealed_to_the_public_key_and_opened_with_the_private_one(pair: Pair) -> None:
    stored = encrypt(PLAIN)

    assert stored.startswith("v2:") and PLAIN not in stored
    assert decrypt(stored) == PLAIN
    assert encrypt(PLAIN) != stored  # a fresh ephemeral key each time


def test_the_api_process_can_seal_a_key_but_cannot_open_one(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = encrypt(PLAIN)
    api_only(monkeypatch)

    assert encrypt("another-key-123456").startswith("v2:")
    with pytest.raises(ConfigError, match="KEY_PRIVATE_KEY"):
        decrypt(stored)


def test_a_different_private_key_cannot_open_it(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = encrypt(PLAIN)
    monkeypatch.setenv("KEY_PRIVATE_KEY", new_pair()[1])

    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(stored)


@pytest.mark.parametrize(
    "damage",
    [
        lambda s: s[:-4] + ("AAAA" if not s.endswith("AAAA") else "BBBB"),
        lambda s: s[:12],
        lambda s: "v2:",
        lambda s: "v2:not base64 at all!!",
    ],
)
def test_a_damaged_value_is_refused(pair: Pair, damage: Callable[[str], str]) -> None:
    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(damage(encrypt(PLAIN)))


def test_a_key_sealed_under_an_old_keypair_opens_while_its_private_key_is_listed(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = encrypt(PLAIN)
    old_private = pair[1]
    public, private = new_pair()
    monkeypatch.setenv("KEY_PUBLIC_KEY", public)
    monkeypatch.setenv("KEY_PRIVATE_KEY", private)

    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(stored)
    monkeypatch.setenv("KEY_OLD_PRIVATE_KEYS", old_private)
    assert decrypt(stored) == PLAIN

    moved = reencrypt(stored)  # now sealed to the new public key
    monkeypatch.delenv("KEY_OLD_PRIVATE_KEYS")
    assert decrypt(moved) == PLAIN


def test_a_key_stored_the_old_way_still_opens_and_can_be_upgraded(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = Fernet.generate_key().decode()
    monkeypatch.delenv("KEY_PUBLIC_KEY")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", secret)
    legacy = encrypt(PLAIN)
    assert not legacy.startswith("v2:")  # no public key set: the local-development mode of D-034
    monkeypatch.setenv("KEY_PUBLIC_KEY", pair[0])

    assert decrypt(legacy) == PLAIN
    upgraded = reencrypt(legacy)

    monkeypatch.delenv("KEY_ENCRYPTION_SECRET")  # the old secret is no longer needed
    assert upgraded.startswith("v2:") and decrypt(upgraded) == PLAIN


def test_the_api_starts_with_only_a_public_key_and_the_worker_only_with_a_private_one(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KEY_PRIVATE_KEY")
    check_secret()  # the API: it only seals
    with pytest.raises(ConfigError, match="KEY_PRIVATE_KEY"):
        check_worker_keys()

    monkeypatch.setenv("KEY_PRIVATE_KEY", pair[1])
    monkeypatch.delenv("KEY_PUBLIC_KEY")
    check_worker_keys()  # the worker: it only opens


def test_nothing_set_means_neither_process_starts() -> None:
    with pytest.raises(ConfigError, match="KEY_PUBLIC_KEY"):
        check_secret()
    with pytest.raises(ConfigError, match="KEY_PRIVATE_KEY"):
        check_worker_keys()


@pytest.mark.parametrize("name", ["KEY_PUBLIC_KEY", "KEY_PRIVATE_KEY"])
@pytest.mark.parametrize("bad", ["not-a-key", "", "AAAA"])
def test_a_malformed_key_is_refused_naming_the_setting(
    monkeypatch: pytest.MonkeyPatch, name: str, bad: str
) -> None:
    monkeypatch.setenv(name, bad)
    check = check_secret if name == "KEY_PUBLIC_KEY" else check_worker_keys

    with pytest.raises(ConfigError, match=name):
        check()


def test_make_keys_prints_a_pair_that_works(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_keys.main()

    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines() if "=" in line)
    monkeypatch.setenv("KEY_PUBLIC_KEY", lines["KEY_PUBLIC_KEY"])
    monkeypatch.setenv("KEY_PRIVATE_KEY", lines["KEY_PRIVATE_KEY"])
    assert decrypt(encrypt(PLAIN)) == PLAIN
    assert lines["KEY_PUBLIC_KEY"] != lines["KEY_PRIVATE_KEY"]


def test_upgrading_every_stored_key_to_the_sealed_format(
    sign_in: SignIn,
    config_file: object,
    queue: StubQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = Fernet.generate_key().decode()
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", secret)  # an install from before this change
    ada, bob = sign_in("ada"), sign_in("bob")
    ids = [make_fighter(ada), make_fighter(ada, name="max"), make_fighter(bob)]
    assert all(not _stored(i).startswith("v2:") for i in ids)
    public, private = new_pair()
    monkeypatch.setenv("KEY_PUBLIC_KEY", public)
    monkeypatch.setenv("KEY_PRIVATE_KEY", private)

    assert rotate_keys.rotate_all() == 3

    monkeypatch.delenv("KEY_ENCRYPTION_SECRET")  # nothing needs the old secret any more
    for fighter_id in ids:
        assert _stored(fighter_id).startswith("v2:") and decrypt(_stored(fighter_id))


def test_a_new_fighter_through_the_api_is_stored_sealed(
    sign_in: SignIn,
    config_file: object,
    queue: StubQueue,
    pair: Pair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_only(monkeypatch)  # the API process, which cannot open what it stores
    client: TestClient = sign_in("ada")

    fighter_id = make_fighter(client)

    assert _stored(fighter_id).startswith("v2:")


def _stored(fighter_id: int) -> str:
    version = fighters.current_version(fighter_id)
    assert version is not None
    return version.api_key_encrypted
