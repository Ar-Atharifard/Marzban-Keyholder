from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEYHOLDER_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/keyholder.db"
    admin_key: SecretStr = Field(min_length=32)
    token_encryption_key: SecretStr = SecretStr("")
    public_base_url: str = "https://keyholder.javatechpack.ir"
    marzban_url: str = "http://127.0.0.1:8000"
    marzban_username: SecretStr = SecretStr("")
    marzban_password: SecretStr = SecretStr("")
    marzban_token: SecretStr = SecretStr("")
    allowed_cdn_hosts: tuple[str, ...] = ()
    cdn_ech_config: str = ""
    profile_source: Literal["policy", "marzban"] = "policy"
    upstream_timeout: float = Field(default=10, ge=1, le=60)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)

    @field_validator("cdn_ech_config")
    @classmethod
    def validate_ech_lookup(cls, value: str) -> str:
        if not value:
            return value
        import re

        lookup, separator, resolver = value.partition("+")
        if separator:
            if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", lookup):
                raise ValueError("Invalid ECH lookup domain")
        else:
            resolver = lookup
        u = urlsplit(resolver)
        if (
            len(value) > 1024
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.path != "/dns-query"
            or u.query
            or u.fragment
        ):
            raise ValueError("ECH requires a dynamic HTTPS DNS resolver")
        # Force port parsing here so invalid ports fail at startup, not on clients.
        _ = u.port
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value():
            from cryptography.fernet import Fernet

            Fernet(value.get_secret_value().encode("ascii"))
        return value

    @field_validator("admin_key")
    @classmethod
    def reject_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().startswith("replace-with-"):
            raise ValueError("Generate an admin key before deployment")
        return value

    @field_validator("public_base_url", "marzban_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            raise ValueError("Expected an HTTP(S) URL without credentials")
        if u.query or u.fragment:
            raise ValueError("URL cannot contain a query or fragment")
        return value.rstrip("/")
