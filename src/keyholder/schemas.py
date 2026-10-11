from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from keyholder.policies import SUPPORTED_KINDS, stored_policy

ProfileKind = Literal[
    "tcp_reality",
    "xhttp_reality",
    "grpc_cdn",
    "tcp_reality_ipv6",
    "shadowsocks_ipv6",
    "ws_tls_cdn",
    "xhttp_tls_cdn",
    "trojan_grpc_cdn",
    "vmess_httpupgrade_cdn",
    "trojan_reality_ipv6",
    "trojan_xhttp_cdn",
]


def default_profiles() -> list[ProfileKind]:
    return ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]


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
    policy: Policy = Field(default_factory=Policy)


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "disabled", "revoked"] | None = None
    policy: Policy | None = None


class CustomerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
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
