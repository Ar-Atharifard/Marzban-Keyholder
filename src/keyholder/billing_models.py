"""Private financial records. Monetary columns contain integer minor units."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from keyholder.models import Base, now


def identity() -> str:
    return str(uuid4())


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="ck_purchase_price"),
        CheckConstraint("currency IN ('IRR','USDT','LTC')", name="ck_purchase_currency"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_days: Mapped[int | None]
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(1000))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_payment_amount"),
        CheckConstraint("currency = 'IRR'", name="ck_payment_currency"),
        CheckConstraint("status IN ('pending','confirmed','void')", name="ck_payment_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8), default="IRR")
    receiving_account: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "uq_payment_reference",
    Payment.receiving_account,
    Payment.reference,
    unique=True,
    sqlite_where=text("reference IS NOT NULL AND status != 'void'"),
)


class Allocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="ck_allocation_amount"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    purchase_id: Mapped[str] = mapped_column(ForeignKey("purchases.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="ck_refund_amount"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Gift(Base):
    __tablename__ = "referral_gifts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    referrer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    referral_ids: Mapped[list[str]] = mapped_column(JSON)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Referral(Base):
    __tablename__ = "customer_referrals"
    __table_args__ = (CheckConstraint("customer_id != referrer_id", name="ck_referral_self"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), unique=True)
    referrer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    introduced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    gift_id: Mapped[str | None] = mapped_column(ForeignKey("referral_gifts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BillingAction(Base):
    """Durable idempotency result and append-only operator action history."""

    __tablename__ = "billing_actions"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Receipt(Base):
    __tablename__ = "payment_receipts"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_receipt_size"),
        CheckConstraint(
            "state IN ('uploading','available','failed','deleting','expired')",
            name="ck_receipt_state",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(128), unique=True)
    version_id: Mapped[str | None] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="uploading", index=True)
    keep: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_reason: Mapped[str | None] = mapped_column(String(64))


class StorageUsage(Base):
    __tablename__ = "storage_usage"
    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StorageReservation(Base):
    __tablename__ = "storage_reservations"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    temporary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
