"""Strict administrator inputs; amounts are decimal strings, never JSON floats."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from keyholder.models import now

Currency = Literal["IRR", "USDT", "LTC"]
Amount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,18})(\.[0-9]{1,8})?$", max_length=28)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Description = Annotated[str, Field(min_length=1, max_length=1000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_dates(cls, value: object) -> object:
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("Include an explicit timezone")
        if isinstance(value, datetime):
            return value.astimezone(UTC)
        return value


class PurchaseInput(Input):
    customer_id: Identifier
    description: Description
    amount: Amount
    currency: Currency = "IRR"
    unit: Literal["currency", "toman"] = "currency"
    quota_bytes: int | None = Field(default=None, ge=0, le=2**63 - 1)
    duration_days: int | None = Field(default=None, ge=0, le=36500)
    purchased_at: datetime = Field(default_factory=now)


class PaymentInput(Input):
    customer_id: Identifier
    amount: Amount
    currency: Literal["IRR"] = "IRR"
    unit: Literal["currency", "toman"] = "currency"
    receiving_account: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    reference: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    notes: str = Field(default="", max_length=1000)
    received_at: datetime = Field(default_factory=now)


class ReasonInput(Input):
    reason: Description


class AllocationInput(Input):
    purchase_id: Identifier
    amount: Amount


class RefundInput(ReasonInput):
    amount: Amount


class ReferralInput(Input):
    customer_id: Identifier
    referrer_id: Identifier
    introduced_at: datetime = Field(default_factory=now)


class GiftInput(Input):
    referrer_id: Identifier
    description: Description
    referral_ids: list[Identifier] = Field(min_length=1, max_length=100)
    delivered_at: datetime = Field(default_factory=now)


class ProtectionInput(ReasonInput):
    keep: bool


class UsageInput(Input):
    size_bytes: int = Field(ge=0, le=2**63 - 1)


class ReservationInput(UsageInput):
    scope: Literal["receipts", "recovery"]
    temporary: bool = False


class CleanupInput(Input):
    execute: bool = False
    pressure: bool = False
