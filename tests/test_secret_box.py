import os

import pytest
from cryptography.fernet import Fernet

from arena.config import ConfigError
from arena_api.secret_box import check_secret, decrypt, encrypt, reencrypt


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())


def test_a_key_comes_back_after_a_round_trip_and_is_not_readable_while_stored() -> None:
    stored = encrypt("sk-live-abcdef123456")

    assert "sk-live" not in stored and "abcdef123456" not in stored
    assert decrypt(stored) == "sk-live-abcdef123456"


def test_the_same_key_encrypts_differently_each_time() -> None:
    assert encrypt("sk-abcdef123456") != encrypt("sk-abcdef123456")


def test_a_different_server_secret_cannot_read_it(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = encrypt("sk-abcdef123456")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(stored)


def test_tampered_data_is_refused() -> None:
    stored = encrypt("sk-abcdef123456")

    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(stored[:-4] + "AAAA")


def test_without_a_server_secret_nothing_is_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KEY_ENCRYPTION_SECRET")

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_SECRET"):
        encrypt("sk-abcdef123456")


def test_a_malformed_server_secret_is_reported_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "not-a-fernet-key")

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_SECRET"):
        encrypt("sk-abcdef123456")


def test_a_valid_secret_passes_the_startup_check() -> None:
    check_secret()


@pytest.mark.parametrize("value", [None, "", "not-a-fernet-key"])
def test_a_missing_or_invalid_secret_fails_the_startup_check(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("KEY_ENCRYPTION_SECRET")
    else:
        monkeypatch.setenv("KEY_ENCRYPTION_SECRET", value)

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_SECRET"):
        check_secret()


def test_a_key_stored_under_an_old_secret_stays_readable_while_that_secret_is_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = os.environ["KEY_ENCRYPTION_SECRET"]
    stored = encrypt("sk-abcdef123456")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

    with pytest.raises(ConfigError, match="could not be decrypted"):
        decrypt(stored)
    monkeypatch.setenv("KEY_ENCRYPTION_OLD_SECRETS", old)

    assert decrypt(stored) == "sk-abcdef123456"


def test_new_keys_are_stored_under_the_current_secret_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEY_ENCRYPTION_OLD_SECRETS", Fernet.generate_key().decode())
    stored = encrypt("sk-abcdef123456")
    monkeypatch.delenv("KEY_ENCRYPTION_OLD_SECRETS")

    assert decrypt(stored) == "sk-abcdef123456"


def test_reencrypting_moves_a_stored_key_to_the_current_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = os.environ["KEY_ENCRYPTION_SECRET"]
    stored = encrypt("sk-abcdef123456")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())
    monkeypatch.setenv("KEY_ENCRYPTION_OLD_SECRETS", old)

    moved = reencrypt(stored)

    monkeypatch.delenv("KEY_ENCRYPTION_OLD_SECRETS")  # the old secret can be dropped now
    assert decrypt(moved) == "sk-abcdef123456"


def test_a_malformed_old_secret_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEY_ENCRYPTION_OLD_SECRETS", "not-a-key")

    with pytest.raises(ConfigError, match="KEY_ENCRYPTION_OLD_SECRETS"):
        check_secret()
