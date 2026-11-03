import pytest
from cryptography.fernet import Fernet

from arena.config import ConfigError
from arena_api.secret_box import decrypt, encrypt


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
