import pytest
from cryptography.fernet import Fernet

from crate.services.crypto import TokenCipher

pytestmark = pytest.mark.unit


def test_encrypt_decrypt_round_trip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    token = "AQBz-refresh-token-value-123"
    assert cipher.decrypt(cipher.encrypt(token)) == token


def test_ciphertext_is_not_plaintext() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt("secret")
    assert "secret" not in ciphertext


def test_decrypt_with_wrong_key_fails() -> None:
    ciphertext = TokenCipher(Fernet.generate_key().decode()).encrypt("secret")
    other = TokenCipher(Fernet.generate_key().decode())
    with pytest.raises(Exception):  # noqa: B017 — any decryption failure is a hard error
        other.decrypt(ciphertext)
