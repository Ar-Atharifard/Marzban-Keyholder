"""Ledger rules shared by every administrator interface."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from keyholder.billing_models import (
    Allocation,
    BillingAction,
    Gift,
    Payment,
    Purchase,
    Referral,
    Refund,
)
from keyholder.models import Customer, now

PRECISION = {"IRR": 0, "USDT": 6, "LTC": 8}


def minor(amount: str, currency: str, unit: str = "currency") -> int:
    if currency not in PRECISION or (unit == "toman" and currency != "IRR"):
        raise HTTPException(422, "Unsupported currency or unit")
    value = Decimal(amount) * 10 ** PRECISION[currency] * (10 if unit == "toman" else 1)
    if not value.is_finite() or value != value.to_integral_value() or not 0 <= value <= 2**63 - 1:
        raise HTTPException(422, "Amount has unsupported precision or range")
    return int(value)


def money(value: int, currency: str) -> str:
    return f"{Decimal(value).scaleb(-PRECISION[currency]):.{PRECISION[currency]}f}"


def timestamp(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value else None


def require[T](db: Session, model: type[T], identifier: str) -> T:
    row = db.get(model, identifier)
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


def mutate(
    db: Session, key: str, operation: str, body: dict[str, Any], work: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Serialize short SQLite writes; replay the original result after uncertain responses."""
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        previous = db.get(BillingAction, key)
        if previous:
            if previous.operation != operation or previous.request_hash != digest:
                raise HTTPException(409, "Idempotency key was used for a different request")
            result = previous.result
        else:
            result = work()
            db.add(
                BillingAction(
                    key=key, operation=operation, request_hash=digest, details=body, result=result
                )
            )
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicting record or duplicate transaction reference") from None
    except BaseException:
        db.rollback()
        raise


def allocated(db: Session, *, payment_id: str | None = None, purchase_id: str | None = None) -> int:
    query = select(Allocation).where(Allocation.reversed_at.is_(None))
    if payment_id:
        query = query.where(Allocation.payment_id == payment_id)
    if purchase_id:
        query = query.where(Allocation.purchase_id == purchase_id)
    return sum(a.amount_minor for a in db.scalars(query))


def refunded(db: Session, payment_id: str) -> int:
    return sum(
        r.amount_minor for r in db.scalars(select(Refund).where(Refund.payment_id == payment_id))
    )


def payment_view(db: Session, row: Payment) -> dict[str, Any]:
    refunds = refunded(db, row.id)
    allocations = allocated(db, payment_id=row.id)
    net = row.amount_minor - refunds if row.status == "confirmed" else 0
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "amount": money(row.amount_minor, row.currency),
        "currency": row.currency,
        "method": "bank",
        "receiving_account": row.receiving_account,
        "reference": row.reference,
        "notes": row.notes,
        "status": row.status,
        "received_at": timestamp(row.received_at),
        "created_at": timestamp(row.created_at),
        "confirmed_at": timestamp(row.confirmed_at),
        "voided_at": timestamp(row.voided_at),
        "refunded": money(refunds, row.currency),
        "allocated": money(allocations, row.currency),
        "unallocated": money(net - allocations, row.currency),
        "possible_duplicate": bool(
            db.scalar(
                select(Payment.id)
                .where(
                    Payment.id != row.id,
                    Payment.customer_id == row.customer_id,
                    Payment.receiving_account == row.receiving_account,
                    Payment.amount_minor == row.amount_minor,
                    Payment.received_at == row.received_at,
                    Payment.status != "void",
                )
                .limit(1)
            )
        ),
    }


def purchase_view(db: Session, row: Purchase) -> dict[str, Any]:
    paid = allocated(db, purchase_id=row.id)
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "description": row.description,
        "amount": money(row.price_minor, row.currency),
        "currency": row.currency,
        "paid": money(paid, row.currency),
        "outstanding": money(row.price_minor - paid, row.currency),
        "quota_bytes": row.quota_bytes,
        "duration_days": row.duration_days,
        "purchased_at": timestamp(row.purchased_at),
        "created_at": timestamp(row.created_at),
        "cancelled_at": timestamp(row.cancelled_at),
        "cancellation_reason": row.cancellation_reason,
    }


def qualifying(db: Session, customer_id: str) -> bool:
    return any(
        p.amount_minor > refunded(db, p.id)
        for p in db.scalars(
            select(Payment).where(Payment.customer_id == customer_id, Payment.status == "confirmed")
        )
    )


def referral_view(db: Session, row: Referral) -> dict[str, Any]:
    qualifies = qualifying(db, row.customer_id)
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "referrer_id": row.referrer_id,
        "introduced_at": timestamp(row.introduced_at),
        "created_at": timestamp(row.created_at),
        "gift_id": row.gift_id,
        "qualifies": qualifies,
        "eligible": qualifies and row.gift_id is None,
    }


def gift_view(row: Gift) -> dict[str, Any]:
    return {
        "id": row.id,
        "referrer_id": row.referrer_id,
        "description": row.description,
        "referral_ids": row.referral_ids,
        "delivered_at": timestamp(row.delivered_at),
        "created_at": timestamp(row.created_at),
        "reversed_at": timestamp(row.reversed_at),
    }


def create_purchase(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    require(db, Customer, values["customer_id"])
    row = Purchase(
        **{k: v for k, v in values.items() if k not in {"amount", "unit"}},
        price_minor=minor(values["amount"], values["currency"], values["unit"]),
    )
    db.add(row)
    db.flush()
    return purchase_view(db, row)


def create_payment(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    require(db, Customer, values["customer_id"])
    amount = minor(values["amount"], values["currency"], values["unit"])
    if not amount:
        raise HTTPException(422, "Payment must be positive")
    row = Payment(
        **{k: v for k, v in values.items() if k not in {"amount", "unit"}}, amount_minor=amount
    )
    db.add(row)
    db.flush()
    return payment_view(db, row)


def payment_action(
    db: Session, identifier: str, action: str, values: dict[str, Any]
) -> dict[str, Any]:
    row = require(db, Payment, identifier)
    if action == "confirm":
        if row.status != "pending":
            raise HTTPException(409, "Only pending payments can be confirmed")
        row.status, row.confirmed_at = "confirmed", now()
    elif action == "void":
        if row.status == "void" or refunded(db, row.id):
            raise HTTPException(
                409, "Already void or refunded; use the existing correction history"
            )
        row.status, row.voided_at = "void", now()
        for allocation in db.scalars(
            select(Allocation).where(
                Allocation.payment_id == row.id, Allocation.reversed_at.is_(None)
            )
        ):
            allocation.reversed_at = now()
    elif action == "refund":
        amount = minor(values["amount"], row.currency)
        if (
            row.status != "confirmed"
            or amount <= 0
            or amount > row.amount_minor - refunded(db, row.id)
        ):
            raise HTTPException(409, "Refund exceeds remaining confirmed funds")
        if allocated(db, payment_id=row.id) > row.amount_minor - refunded(db, row.id) - amount:
            raise HTTPException(409, "Reverse affected allocations before refunding")
        db.add(Refund(payment_id=row.id, amount_minor=amount, reason=values["reason"]))
    elif action == "allocate":
        purchase = require(db, Purchase, values["purchase_id"])
        amount = minor(values["amount"], row.currency)
        if (
            row.status != "confirmed"
            or purchase.cancelled_at
            or purchase.customer_id != row.customer_id
            or purchase.currency != row.currency
        ):
            raise HTTPException(
                409, "Allocation requires a confirmed payment and matching open purchase"
            )
        if (
            amount <= 0
            or amount > row.amount_minor - refunded(db, row.id) - allocated(db, payment_id=row.id)
            or amount > purchase.price_minor - allocated(db, purchase_id=purchase.id)
        ):
            raise HTTPException(409, "Allocation exceeds available funds or purchase balance")
        allocation = Allocation(payment_id=row.id, purchase_id=purchase.id, amount_minor=amount)
        db.add(allocation)
        db.flush()
        return {
            "id": allocation.id,
            "payment_id": row.id,
            "purchase_id": purchase.id,
            "amount": money(amount, row.currency),
        }
    else:
        raise HTTPException(422, "Unknown payment action")
    db.flush()
    return payment_view(db, row)


def create_referral(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    require(db, Customer, values["customer_id"])
    require(db, Customer, values["referrer_id"])
    seen = {values["customer_id"]}
    current = values["referrer_id"]
    while current:
        if current in seen:
            raise HTTPException(409, "Referral would create a cycle")
        seen.add(current)
        parent = db.scalar(select(Referral).where(Referral.customer_id == current))
        current = parent.referrer_id if parent else ""
    row = Referral(**values)
    db.add(row)
    db.flush()
    return referral_view(db, row)


def create_gift(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    ids = values["referral_ids"]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Select unique referrals")
    rows = [require(db, Referral, rid) for rid in ids]
    if any(
        r.referrer_id != values["referrer_id"] or r.gift_id or not qualifying(db, r.customer_id)
        for r in rows
    ):
        raise HTTPException(409, "Every selected referral must be eligible for this recommender")
    row = Gift(**values)
    db.add(row)
    db.flush()
    for referral in rows:
        referral.gift_id = row.id
    return gift_view(row)
