"""Fernet-based encryption for secrets stored at rest (Facebook Page tokens)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    """Encrypt/decrypt short secret strings with a Fernet key."""

    def __init__(self, encryption_key: str) -> None:
        try:
            self._cipher = Fernet(encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("CONFIG_ENCRYPTION_KEY is not a valid Fernet key") from exc

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Stored credentials cannot be decrypted. "
                "Restore the original CONFIG_ENCRYPTION_KEY."
            ) from exc
