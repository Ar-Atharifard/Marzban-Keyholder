import base64
import binascii
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProfileKind = Literal["xhttp_reality", "tcp_reality", "xhttp_cdn", "ws_cdn"]


def default_profiles() -> list[ProfileKind]:
    return ["xhttp_reality", "tcp_reality", "xhttp_cdn", "ws_cdn"]


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: list[ProfileKind] = Field(
        default_factory=default_profiles,
        max_length=4,
    )
    ech_enabled: bool = False
    include_base_cdn: bool = True
    # Future generators add validated policy fields; no arbitrary Xray overrides.


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


class TokenResult(BaseModel):
    customer: CustomerView
    subscription_url: str
    token: str


class ECHSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ech_config_list: str = Field(max_length=16384)

    @field_validator("ech_config_list")
    @classmethod
    def validate_ech(cls, value: str) -> str:
        if not value:
            return value
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("ECH must be standard base64") from exc
        if len(raw) < 4 or int.from_bytes(raw[:2], "big") != len(raw) - 2:
            raise ValueError("Invalid ECHConfigList length framing")
        return value
