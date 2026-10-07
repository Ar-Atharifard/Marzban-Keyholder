import hashlib
import hmac
import re
import secrets

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def valid_token(token: str) -> bool:
    return TOKEN_RE.fullmatch(token) is not None


def verify_token(token: str, digest: str) -> bool:
    return valid_token(token) and hmac.compare_digest(hash_token(token), digest)
