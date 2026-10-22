from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from keyholder.profile_types import SUPPORTED_KINDS


class BackendConfig(BaseModel):
    """Server-owned adapter configuration; never accepted in customer requests."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    provider: Literal["marzban", "http_subscription"] = "marzban"
    config_ref: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    url: str = Field(repr=False)
    token: SecretStr = Field(default=SecretStr(""), repr=False)
    username: SecretStr = Field(default=SecretStr(""), repr=False)
    password: SecretStr = Field(default=SecretStr(""), repr=False)

    @model_validator(mode="after")
    def validate_source(self) -> "BackendConfig":
        from string import Formatter

        fields = [name for _, name, _, _ in Formatter().parse(self.url) if name is not None]
        if self.provider == "http_subscription":
            if fields != ["username"] or self.url.count("{username}") != 1:
                raise ValueError("Subscription URL needs one literal {username} placeholder")
            if self.username.get_secret_value() or self.password.get_secret_value():
                raise ValueError("Subscription adapter supports bearer authentication only")
        elif fields:
            raise ValueError("Panel URL cannot contain placeholders")
        u = urlsplit(self.url.replace("{username}", "account"))
        if (
            u.scheme not in {"http", "https"}
            or not u.hostname
            or u.username
            or u.password
            or u.fragment
            or any(ord(c) <= 32 or ord(c) == 127 for c in self.url)
            or (self.provider == "marzban" and u.query)
            or "{username}" in self.url.split("/", 3)[2]
        ):
            raise ValueError("Invalid upstream URL")
        _ = u.port
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KEYHOLDER_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    database_url: str = "sqlite:///./data/keyholder.db"
    admin_key: SecretStr = Field(min_length=32)
    token_encryption_key: SecretStr = SecretStr("")
    public_base_url: str = "https://subscription.example.invalid"
    marzban_url: str = "http://127.0.0.1:8000"
    marzban_username: SecretStr = SecretStr("")
    marzban_password: SecretStr = SecretStr("")
    marzban_token: SecretStr = SecretStr("")
    allowed_cdn_hosts: tuple[str, ...] = ()
    cdn_ech_config: str = ""
    cdn_tls_compatibility: bool = False
    cdn_ech_kinds: tuple[str, ...] = SUPPORTED_KINDS
    cdn_ech_full_catalog: tuple[str, ...] = ()
    default_inbound_tags: tuple[str, ...] = ()
    profile_source: Literal["policy", "marzban", "upstream"] = "policy"
    backends: list[BackendConfig] = Field(default_factory=list, repr=False)
    # Configured CIDRs are a trusted deployment decision, never imported from links.
    allowed_cdn_networks: tuple[str, ...] = ()
    enabled_profiles: tuple[str, ...] = SUPPORTED_KINDS
    upstream_timeout: float = Field(default=10, ge=1, le=60)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)

    @field_validator("backends")
    @classmethod
    def unique_backends(cls, value: list[BackendConfig]) -> list[BackendConfig]:
        if len({b.id for b in value}) != len(value):
            raise ValueError("Backend IDs must be unique")
        return value

    @field_validator("allowed_cdn_networks")
    @classmethod
    def validate_networks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        import ipaddress

        return tuple(str(ipaddress.ip_network(v, strict=True)) for v in value)

    @field_validator("enabled_profiles", "cdn_ech_kinds")
    @classmethod
    def validate_profiles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from keyholder.policies import SUPPORTED_KINDS

        if not set(value) <= set(SUPPORTED_KINDS):
            raise ValueError("Unknown enabled profile")
        return tuple(dict.fromkeys(value))

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
