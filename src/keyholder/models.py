from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Backend(Base):
    __tablename__ = "backends"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="marzban")
    # Environment prefix references, never credentials or caller-controlled URLs.
    config_ref: Mapped[str] = mapped_column(String(64), default="default")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled', 'revoked')", name="ck_customer_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping: Mapped["CustomerMapping"] = relationship(cascade="all, delete-orphan", uselist=False)


class CustomerMapping(Base):
    __tablename__ = "customer_mappings"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    backend_id: Mapped[str] = mapped_column(ForeignKey("backends.id"))
    upstream_username: Mapped[str] = mapped_column(String(32))


class ApplicationData(Base):
    __tablename__ = "application_data"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
