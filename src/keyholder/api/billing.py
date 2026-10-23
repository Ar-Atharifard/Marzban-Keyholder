"""Private ledger API. No routes here are exposed by subscription ingress."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select

from keyholder import billing as ledger
from keyholder.api.dependencies import DB, admin
from keyholder.billing_models import (
    Allocation,
    BillingAction,
    Gift,
    Payment,
    Purchase,
    Referral,
    Refund,
)
from keyholder.billing_schemas import (
    AllocationInput,
    GiftInput,
    PaymentInput,
    PurchaseInput,
    ReasonInput,
    ReferralInput,
    RefundInput,
)
from keyholder.models import Customer, now

router = APIRouter(prefix="/admin", dependencies=[Depends(admin)])
Key = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("/purchases", status_code=201)
def purchase_create(body: PurchaseInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "purchase.create",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: ledger.create_purchase(db, body.model_dump()),
    )


@router.post("/payments", status_code=201)
def payment_create(body: PaymentInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "payment.create",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: ledger.create_payment(db, body.model_dump()),
    )


@router.get("/purchases")
def purchases(
    db: DB, customer_id: str | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    query = select(Purchase)
    if customer_id:
        query = query.where(Purchase.customer_id == customer_id)
    return [
        ledger.purchase_view(db, p)
        for p in db.scalars(
            query.order_by(Purchase.purchased_at.desc(), Purchase.id).limit(limit).offset(offset)
        )
    ]


@router.get("/purchases/{identifier}")
def purchase_get(identifier: str, db: DB) -> dict[str, Any]:
    return ledger.purchase_view(db, ledger.require(db, Purchase, identifier))


@router.post("/purchases/{identifier}/cancel")
def purchase_cancel(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        row = ledger.require(db, Purchase, identifier)
        if row.cancelled_at or ledger.allocated(db, purchase_id=row.id):
            raise HTTPException(409, "Already cancelled or has active allocations")
        row.cancelled_at, row.cancellation_reason = now(), body.reason
        return ledger.purchase_view(db, row)

    return ledger.mutate(db, key, "purchase.cancel", {"id": identifier, **body.model_dump()}, work)


@router.get("/payments")
def payments(
    db: DB, customer_id: str | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    query = select(Payment)
    if customer_id:
        query = query.where(Payment.customer_id == customer_id)
    return [
        ledger.payment_view(db, p)
        for p in db.scalars(
            query.order_by(Payment.received_at.desc(), Payment.id).limit(limit).offset(offset)
        )
    ]


@router.get("/payments/{identifier}")
def payment_get(identifier: str, db: DB) -> dict[str, Any]:
    return ledger.payment_view(db, ledger.require(db, Payment, identifier))


@router.post("/payments/{identifier}/confirm")
def payment_confirm(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "payment.confirm",
        {"id": identifier, **body.model_dump()},
        lambda: ledger.payment_action(db, identifier, "confirm", body.model_dump()),
    )


@router.post("/payments/{identifier}/void")
def payment_void(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "payment.void",
        {"id": identifier, **body.model_dump()},
        lambda: ledger.payment_action(db, identifier, "void", body.model_dump()),
    )


@router.post("/payments/{identifier}/refunds", status_code=201)
def payment_refund(identifier: str, body: RefundInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "payment.refund",
        {"id": identifier, **body.model_dump()},
        lambda: ledger.payment_action(db, identifier, "refund", body.model_dump()),
    )


@router.get("/payments/{identifier}/refunds")
def payment_refunds(
    identifier: str, db: DB, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    payment = ledger.require(db, Payment, identifier)
    return [
        {
            "id": r.id,
            "payment_id": r.payment_id,
            "amount": ledger.money(r.amount_minor, payment.currency),
            "reason": r.reason,
            "created_at": ledger.timestamp(r.created_at),
        }
        for r in db.scalars(
            select(Refund)
            .where(Refund.payment_id == identifier)
            .order_by(Refund.created_at, Refund.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/payments/{identifier}/allocations", status_code=201)
def payment_allocate(identifier: str, body: AllocationInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "payment.allocate",
        {"id": identifier, **body.model_dump()},
        lambda: ledger.payment_action(db, identifier, "allocate", body.model_dump()),
    )


@router.get("/payments/{identifier}/allocations")
def payment_allocations(
    identifier: str, db: DB, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    payment = ledger.require(db, Payment, identifier)
    return [
        {
            "id": a.id,
            "payment_id": a.payment_id,
            "purchase_id": a.purchase_id,
            "amount": ledger.money(a.amount_minor, payment.currency),
            "reversed_at": ledger.timestamp(a.reversed_at),
        }
        for a in db.scalars(
            select(Allocation)
            .where(Allocation.payment_id == identifier)
            .order_by(Allocation.created_at, Allocation.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/allocations/{identifier}/reverse")
def allocation_reverse(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        row = ledger.require(db, Allocation, identifier)
        if row.reversed_at:
            raise HTTPException(409, "Allocation already reversed")
        row.reversed_at = now()
        return {"id": row.id, "reversed_at": ledger.timestamp(row.reversed_at)}

    return ledger.mutate(
        db, key, "allocation.reverse", {"id": identifier, **body.model_dump()}, work
    )


@router.get("/customers/{identifier}/balances")
def balances(identifier: str, db: DB) -> dict[str, Any]:
    ledger.require(db, Customer, identifier)
    result = {}
    for currency in ledger.PRECISION:
        outstanding = sum(
            p.price_minor - ledger.allocated(db, purchase_id=p.id)
            for p in db.scalars(
                select(Purchase).where(
                    Purchase.customer_id == identifier,
                    Purchase.currency == currency,
                    Purchase.cancelled_at.is_(None),
                )
            )
        )
        unallocated = sum(
            p.amount_minor - ledger.refunded(db, p.id) - ledger.allocated(db, payment_id=p.id)
            for p in db.scalars(
                select(Payment).where(
                    Payment.customer_id == identifier,
                    Payment.currency == currency,
                    Payment.status == "confirmed",
                )
            )
        )
        result[currency] = {
            "outstanding": ledger.money(outstanding, currency),
            "unallocated": ledger.money(unallocated, currency),
        }
    return {"customer_id": identifier, "balances": result}


@router.post("/referrals", status_code=201)
def referral_create(body: ReferralInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "referral.create",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: ledger.create_referral(db, body.model_dump()),
    )


@router.get("/referrals")
def referrals(
    db: DB,
    referrer_id: str | None = None,
    state: Literal["all", "eligible", "considered"] = "all",
    limit: Limit = 50,
    offset: Offset = 0,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    query = select(Referral)
    if referrer_id:
        query = query.where(Referral.referrer_id == referrer_id)
    for boundary in (since, until):
        if boundary is not None and boundary.utcoffset() is None:
            raise HTTPException(422, "Date filters require a timezone")
    if since:
        query = query.where(Referral.introduced_at >= since.astimezone(UTC))
    if until:
        query = query.where(Referral.introduced_at < until.astimezone(UTC))
    if since and until and since >= until:
        raise HTTPException(422, "Date range must be increasing")
    # Qualification is based on confirmed funds, including refunds, rather than a cached flag.
    from sqlalchemy import exists, func

    refunds = (
        select(func.coalesce(func.sum(Refund.amount_minor), 0))
        .where(Refund.payment_id == Payment.id)
        .correlate(Payment)
        .scalar_subquery()
    )
    paid = exists(
        select(Payment.id).where(
            Payment.customer_id == Referral.customer_id,
            Payment.status == "confirmed",
            Payment.amount_minor > refunds,
        )
    )
    if state == "eligible":
        query = query.where(Referral.gift_id.is_(None), paid)
    elif state == "considered":
        query = query.where(Referral.gift_id.is_not(None))
    return [
        ledger.referral_view(db, r)
        for r in db.scalars(
            query.order_by(Referral.introduced_at, Referral.id).limit(limit).offset(offset)
        )
    ]


@router.post("/gifts", status_code=201)
def gift_create(body: GiftInput, db: DB, key: Key) -> dict[str, Any]:
    return ledger.mutate(
        db,
        key,
        "gift.create",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: ledger.create_gift(db, body.model_dump()),
    )


@router.get("/gifts")
def gifts(
    db: DB, referrer_id: str | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    query = select(Gift)
    if referrer_id:
        query = query.where(Gift.referrer_id == referrer_id)
    result = []
    for row in db.scalars(
        query.order_by(Gift.delivered_at.desc(), Gift.id).limit(limit).offset(offset)
    ):
        result.append(
            {
                **ledger.gift_view(row),
                "qualification_changed": any(
                    not ledger.qualifying(db, ledger.require(db, Referral, rid).customer_id)
                    for rid in row.referral_ids
                ),
            }
        )
    return result


@router.post("/gifts/{identifier}/reverse")
def gift_reverse(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        row = ledger.require(db, Gift, identifier)
        if row.reversed_at:
            raise HTTPException(409, "Gift already reversed")
        row.reversed_at = now()
        for referral in db.scalars(select(Referral).where(Referral.gift_id == row.id)):
            referral.gift_id = None
        return ledger.gift_view(row)

    return ledger.mutate(db, key, "gift.reverse", {"id": identifier, **body.model_dump()}, work)


@router.get("/billing/actions")
def actions(db: DB, limit: Limit = 50, offset: Offset = 0) -> list[dict[str, Any]]:
    return [
        {
            "key": a.key,
            "operation": a.operation,
            "details": a.details,
            "result": a.result,
            "created_at": ledger.timestamp(a.created_at),
        }
        for a in db.scalars(
            select(BillingAction)
            .order_by(BillingAction.created_at.desc(), BillingAction.key)
            .limit(limit)
            .offset(offset)
        )
    ]
