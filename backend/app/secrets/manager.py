import base64
import hashlib
import logging
import secrets as stdlib_secrets

from cryptography.fernet import Fernet

PREFIX = "fernet:"


def _encoding_key(app_secret_key: str, configured_key: str = "") -> bytes:
    if configured_key:
        candidate = configured_key.encode()
        try:
            Fernet(candidate).encrypt(b"probe")
            return candidate
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "Configured secret encryption key rejected: %s", type(exc).__name__
            )
    digest = hashlib.sha256(f"{app_secret_key}:botq-secret-envelope-v1".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(value: str, app_secret_key: str, configured_key: str = "") -> str:
    f = Fernet(_encoding_key(app_secret_key, configured_key))
    return PREFIX + f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str, app_secret_key: str, configured_key: str = "") -> str:
    if not encrypted.startswith(PREFIX):
        raise ValueError("Encrypted value has unknown format")
    f = Fernet(_encoding_key(app_secret_key, configured_key))
    return f.decrypt(encrypted[len(PREFIX) :].encode()).decode()


def key_hint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def random_secret_value() -> str:
    return stdlib_secrets.token_urlsafe(48)
