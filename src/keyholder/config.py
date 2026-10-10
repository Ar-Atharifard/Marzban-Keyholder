from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEYHOLDER_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/keyholder.db"
    admin_key: SecretStr = Field(min_length=32)
    public_base_url: str = "https://keyholder.javatechpack.ir"
    marzban_url: str = "http://127.0.0.1:8000"
    marzban_username: SecretStr = SecretStr("")
    marzban_password: SecretStr = SecretStr("")
    marzban_token: SecretStr = SecretStr("")
    upstream_timeout: float = Field(default=10, ge=1, le=60)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)

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
