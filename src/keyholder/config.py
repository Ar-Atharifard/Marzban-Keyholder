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
    upstream_connect_timeout: float = Field(default=5, ge=0.1, le=60)
    upstream_max_connections: int = Field(default=20, ge=1, le=10000)
    upstream_max_keepalive_connections: int = Field(default=10, ge=0, le=10000)
    upstream_keepalive_expiry: float = Field(default=5, ge=0.1, le=300)
    sqlite_busy_timeout: float = Field(default=5, ge=0.1, le=60)
    storage_enabled: bool = False
    storage_cleanup_enabled: bool = False
    storage_recovery_cleanup_enabled: bool = False
    storage_total_bytes: int = Field(default=10_000_000_000, gt=0)
    storage_receipt_bytes: int = Field(default=2_000_000_000, gt=0)
    storage_recovery_bytes: int = Field(default=6_000_000_000, gt=0)
    storage_headroom_bytes: int = Field(default=2_000_000_000, ge=0)
    storage_other_bytes: int = Field(default=0, ge=0)
    storage_usage_max_age_seconds: int = Field(default=86400, ge=60, le=604800)
    receipt_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=5 * 1024 * 1024)
    receipt_retention_days: int = Field(default=180, ge=30, le=3650)
    receipt_protect_days: int = Field(default=30, ge=1, le=3650)
    receipt_s3_endpoint: str = ""
    receipt_s3_region: str = ""
    receipt_s3_bucket: str = ""
    receipt_s3_access_key: SecretStr = Field(default=SecretStr(""), repr=False)
    receipt_s3_secret_key: SecretStr = Field(default=SecretStr(""), repr=False)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    rate_limit_max_keys: int = Field(default=10000, ge=1, le=1000000)
    xray_client_socks_port: int = Field(default=10808, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_connection_limits(self) -> "Settings":
        if self.upstream_max_keepalive_connections > self.upstream_max_connections:
            raise ValueError("Keepalive connections cannot exceed total connections")
        return self

    @model_validator(mode="after")
    def validate_storage(self) -> "Settings":
        if (
            self.storage_receipt_bytes
            + self.storage_recovery_bytes
            + self.storage_headroom_bytes
            + self.storage_other_bytes
            > self.storage_total_bytes
        ):
            raise ValueError("Storage budgets and other usage exceed total capacity")
        if self.receipt_protect_days > self.receipt_retention_days:
            raise ValueError("Receipt protection exceeds retention")
        values = [
            self.receipt_s3_endpoint,
            self.receipt_s3_region,
            self.receipt_s3_bucket,
            self.receipt_s3_access_key.get_secret_value(),
            self.receipt_s3_secret_key.get_secret_value(),
        ]
        if any(values) and not all(values):
            raise ValueError("Complete receipt storage configuration is required")
        if self.storage_cleanup_enabled and not all(values):
            raise ValueError("Automatic receipt cleanup requires receipt storage configuration")
        if self.receipt_s3_endpoint:
            u = urlsplit(self.receipt_s3_endpoint)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.username
                or u.password
                or u.query
                or u.fragment
                or u.path not in {"", "/"}
            ):
                raise ValueError("Receipt storage requires a trusted HTTPS S3 endpoint")
            if not self.storage_enabled:
                raise ValueError("Enable storage budgets before configuring receipts")
        return self

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
