from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialConfigurationError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


class CredentialCipher:
    """Authenticated encryption whose master key is supplied outside the database."""

    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None = None
        if key:
            try:
                self._fernet = Fernet(key.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise CredentialConfigurationError(
                    "CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key"
                ) from exc

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, secret: str) -> str:
        if self._fernet is None:
            raise CredentialConfigurationError("credential encryption is not configured")
        return self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_secret: str) -> str:
        if self._fernet is None:
            raise CredentialConfigurationError("credential encryption is not configured")
        try:
            return self._fernet.decrypt(encrypted_secret.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise CredentialDecryptionError("stored credential cannot be decrypted") from exc


def secret_hint(secret: str) -> str:
    # Never reveal an entire short credential. Normal provider keys expose only
    # their last four characters so users can distinguish replacements.
    tail = secret[-4:] if len(secret) > 8 else ""
    return f"••••{tail}"
