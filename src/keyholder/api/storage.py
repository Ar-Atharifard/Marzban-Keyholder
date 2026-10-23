"""Authenticated attachment transport and shared storage admission control."""

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from keyholder import billing, storage
from keyholder.api.billing import Key, Limit, Offset
from keyholder.api.dependencies import DB, admin
from keyholder.billing_models import Payment, Receipt, StorageReservation
from keyholder.billing_schemas import (
    CleanupInput,
    ProtectionInput,
    ReasonInput,
    ReservationInput,
    UsageInput,
)
from keyholder.models import now
from keyholder.object_storage import ObjectStorage

router = APIRouter(prefix="/admin", dependencies=[Depends(admin)])


def store(request: Request) -> ObjectStorage:
    value: ObjectStorage | None = request.app.state.receipt_store
    if value is None:
        raise HTTPException(503, "Receipt object storage is not configured")
    return value


@router.get("/storage")
def storage_status(request: Request, db: DB) -> dict[str, Any]:
    return storage.usage(db, request.app.state.settings)


@router.get("/storage/reservations")
def reservations(db: DB, limit: Limit = 50, offset: Offset = 0) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "scope": r.scope,
            "size_bytes": r.size_bytes,
            "temporary": r.temporary,
            "created_at": billing.timestamp(r.created_at),
        }
        for r in db.scalars(
            select(StorageReservation)
            .order_by(StorageReservation.created_at, StorageReservation.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/storage/reconcile")
def reconcile(request: Request) -> dict[str, Any]:
    with storage.receipt_lock(request.app.state.sessions):
        if request.app.state.receipt_store is None:
            with request.app.state.sessions() as db:
                if db.scalar(select(Receipt.id).where(Receipt.state != "expired").limit(1)):
                    raise HTTPException(
                        503, "Configure receipt storage before reconciling existing attachments"
                    )
        storage.reconcile(request.app.state.sessions, request.app.state.receipt_store)
    with request.app.state.sessions() as db:
        return storage.usage(db, request.app.state.settings)


@router.put("/storage/usage/recovery")
def report_recovery(body: UsageInput, db: DB) -> dict[str, Any]:
    db.execute(text("BEGIN IMMEDIATE"))
    storage.report(db, "recovery", body.size_bytes)
    db.commit()
    return {"scope": "recovery", "size_bytes": body.size_bytes}


@router.post("/storage/reservations/{identifier}")
def reservation_create(
    identifier: str, body: ReservationInput, request: Request, db: DB
) -> dict[str, Any]:
    if not 16 <= len(identifier) <= 128 or identifier == "receipt-io":
        raise HTTPException(422, "Invalid reservation identity")
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        result = storage.reserve(
            db, request.app.state.settings, identifier, body.scope, body.size_bytes, body.temporary
        )
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


@router.post("/storage/reservations/{identifier}/release")
def reservation_release(identifier: str, body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        row = billing.require(db, StorageReservation, identifier)
        db.delete(row)
        return {"id": identifier, "released": True, "reason": body.reason}

    return billing.mutate(db, key, "storage.release", {"id": identifier, **body.model_dump()}, work)


@router.post("/storage/capture/start")
def capture_start(body: ReasonInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        db.add(StorageReservation(id="receipt-io", scope="lock", size_bytes=0))
        db.flush()
        return {"lock": "receipt-io", "captured_at": billing.timestamp(now())}

    return billing.mutate(db, key, "storage.capture", body.model_dump(), work)


@router.get("/storage/receipt-manifest")
def receipt_manifest(db: DB, limit: Limit = 100, offset: Offset = 0) -> list[dict[str, Any]]:
    return [
        {**storage.receipt_view(r), "object_key": r.object_key, "version_id": r.version_id}
        for r in db.scalars(
            select(Receipt)
            .where(Receipt.state == "available")
            .order_by(Receipt.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/storage/receipts/cleanup")
def receipt_cleanup(body: CleanupInput, request: Request) -> dict[str, Any]:
    with storage.receipt_lock(request.app.state.sessions):
        return storage.cleanup(
            request.app.state.sessions,
            request.app.state.settings,
            store(request),
            execute=body.execute,
            pressure=body.pressure,
        )


@router.get("/payments/{identifier}/receipts")
def receipts(
    identifier: str, db: DB, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    billing.require(db, Payment, identifier)
    return [
        storage.receipt_view(r)
        for r in db.scalars(
            select(Receipt)
            .where(Receipt.payment_id == identifier)
            .order_by(Receipt.created_at, Receipt.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/payments/{identifier}/receipts", status_code=201)
async def receipt_upload(identifier: str, request: Request, key: Key) -> dict[str, Any]:
    backend = store(request)
    maximum = request.app.state.settings.receipt_max_bytes
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > maximum:
            raise HTTPException(413, "Receipt exceeds size limit")
    media_type = request.headers.get("content-type", "").split(";", 1)[0]
    return await run_in_threadpool(
        storage.upload,
        request.app.state.sessions,
        request.app.state.settings,
        backend,
        identifier,
        key,
        bytes(raw),
        media_type,
    )


@router.get("/receipts/{identifier}/content")
def receipt_download(identifier: str, request: Request, db: DB) -> Response:
    row = billing.require(db, Receipt, identifier)
    if row.state != "available" or row.version_id is None:
        raise HTTPException(410, "Receipt content is unavailable or expired")
    # End the read transaction before object-storage I/O.
    data_row = (row.object_key, row.version_id, row.media_type, row.sha256, row.size_bytes)
    db.rollback()
    data = store(request).get(
        data_row[0], data_row[1], request.app.state.settings.receipt_max_bytes
    )
    if len(data) != data_row[4] or hashlib.sha256(data).hexdigest() != data_row[3]:
        raise HTTPException(503, "Receipt integrity verification failed")
    return Response(
        data,
        media_type=data_row[2],
        headers={
            "Content-Disposition": "attachment; filename=receipt."
            + ("png" if data_row[2] == "image/png" else "jpg")
        },
    )


@router.post("/receipts/{identifier}/restore")
async def receipt_restore(identifier: str, request: Request, key: Key) -> dict[str, Any]:
    backend = store(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > request.app.state.settings.receipt_max_bytes:
            raise HTTPException(413, "Receipt exceeds size limit")
    return await run_in_threadpool(
        storage.restore,
        request.app.state.sessions,
        request.app.state.settings,
        backend,
        identifier,
        bytes(raw),
        request.headers.get("content-type", "").split(";", 1)[0],
    )


@router.post("/receipts/{identifier}/protection")
def protection(identifier: str, body: ProtectionInput, db: DB, key: Key) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        row = billing.require(db, Receipt, identifier)
        if row.state not in {"available", "failed", "uploading"}:
            raise HTTPException(409, "Receipt is being deleted or already expired")
        row.keep = body.keep
        return storage.receipt_view(row)

    return billing.mutate(
        db, key, "receipt.protection", {"id": identifier, **body.model_dump()}, work
    )
