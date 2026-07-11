"""Symmetric encryption for stored Spotify tokens."""

from functools import lru_cache

from cryptography.fernet import Fernet

from crate.settings import get_settings


class TokenCipher:
    """Fernet wrapper working in str space (ciphertext is urlsafe base64)."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


@lru_cache
def get_cipher() -> TokenCipher:
    return TokenCipher(get_settings().encryption_key)
