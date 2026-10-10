"""Authenticated encryption for retrievable bearer tokens; never log plaintext."""

from cryptography.fernet import Fernet, InvalidToken

from keyholder.config import Settings
from keyholder.security import valid_token, verify_token


def encrypt(settings: Settings, token: str) -> str | None:
    key = settings.token_encryption_key.get_secret_value()
    if not key:
        return None  # Legacy deployment compatibility; retrieval explicitly refuses this.
    if not valid_token(token):
        raise ValueError("Invalid token")
    return Fernet(key.encode("ascii")).encrypt(token.encode("ascii")).decode("ascii")


def decrypt(settings: Settings, encrypted: str | None, digest: str) -> str:
    key = settings.token_encryption_key.get_secret_value()
    if not key or not encrypted:
        raise ValueError("Token retrieval unavailable; explicit rotation required")
    try:
        # No ttl: customer URLs have no scheduled expiry.
        token = Fernet(key.encode("ascii")).decrypt(encrypted.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError):
        raise ValueError("Token retrieval unavailable") from None
    if not verify_token(token, digest):
        raise ValueError("Token integrity verification failed")
    return token
