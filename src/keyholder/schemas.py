from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from keyholder.policies import stored_policy
from keyholder.profile_types import DEFAULT_PROFILES, SUPPORTED_KINDS, ProfileKind


def default_profiles() -> list[ProfileKind]:
    return list(DEFAULT_PROFILES)


def normalize_telegram(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    if value.isdecimal() and 1 <= len(value) <= 20:
        return value
    if (
        not 5 <= len(value) <= 32
        or not value[0].isalpha()
        or any(not (char.isascii() and (char.isalnum() or char == "_")) for char in value)
    ):
        raise ValueError("Telegram must be a numeric ID or a 5–32 character username")
    return "@" + value.lower()


def normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().replace(" ", "").replace("-", "")
    if not value.startswith("+") or not value[1:].isascii() or not value[1:].isdecimal():
        raise ValueError("Phone must use international +digits format")
    if not 7 <= len(value[1:]) <= 15:
        raise ValueError("Phone must contain 7–15 digits")
    return value


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: list[ProfileKind] = Field(
        default_factory=default_profiles,
        max_length=len(SUPPORTED_KINDS),
    )


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    backend_id: str = Field(default="marzban-default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    upstream_username: str = Field(pattern=r"^[a-zA-Z0-9_]{3,32}$")


class CustomerCreate(MappingInput):
    name: str = Field(min_length=1, max_length=200)
    telegram: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=16)
    policy: Policy = Field(default_factory=Policy)

    _telegram = field_validator("telegram")(normalize_telegram)
    _phone = field_validator("phone")(normalize_phone)


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    telegram: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=16)
    status: Literal["active", "disabled", "revoked"] | None = None
    policy: Policy | None = None

    _telegram = field_validator("telegram")(normalize_telegram)
    _phone = field_validator("phone")(normalize_phone)


class CustomerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    telegram: str | None
    phone: str | None
    status: str
    policy: Policy
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None
    mapping: MappingInput

    @field_validator("created_at", "updated_at", "revoked_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value

    @field_validator("policy", mode="before")
    @classmethod
    def normalize_stored_policy(cls, value: object) -> object:
        return stored_policy(value) if not isinstance(value, Policy) else value


class TokenResult(BaseModel):
    customer: CustomerView
    subscription_url: str
    token: str


class ErrorResponse(BaseModel):
    detail: str


class BackendView(BaseModel):
    id: str
    provider: str
    config_ref: str
    registered: bool
