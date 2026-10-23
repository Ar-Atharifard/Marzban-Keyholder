"""Quota accounting and receipt lifecycle. External I/O never holds a database write lock."""

import hashlib
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from keyholder.billing import require, timestamp
from keyholder.billing_models import Payment, Receipt, StorageReservation, StorageUsage
from keyholder.config import Settings
from keyholder.models import now
from keyholder.object_storage import ObjectStorage


def utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC)


def usage(db: Session, settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = {
        "enabled": settings.storage_enabled,
        "cleanup_enabled": settings.storage_cleanup_enabled,
        "recovery_cleanup_enabled": settings.storage_recovery_cleanup_enabled,
        "total_bytes": settings.storage_total_bytes,
        "headroom_bytes": settings.storage_headroom_bytes,
        "other_bytes": settings.storage_other_bytes,
        "scopes": {},
    }
    total = settings.storage_other_bytes
    for scope, budget in [
        ("receipts", settings.storage_receipt_bytes),
        ("recovery", settings.storage_recovery_bytes),
    ]:
        row = db.get(StorageUsage, scope)
        reserved = sum(
            r.size_bytes
            for r in db.scalars(select(StorageReservation).where(StorageReservation.scope == scope))
        )
        stale = (
            row is None
            or (now() - utc(row.measured_at)).total_seconds()
            > settings.storage_usage_max_age_seconds
        )
        size = row.size_bytes if row else None
        result["scopes"][scope] = {
            "used_bytes": size,
            "reserved_bytes": reserved,
            "budget_bytes": budget,
            "measured_at": timestamp(row.measured_at) if row else None,
            "stale": stale,
            "percent": round((size + reserved) / budget * 100, 1) if size is not None else None,
        }
        total += (size or 0) + reserved
    result["accounted_bytes"] = total
    result["blocked"] = (
        any(
            s["stale"] or s["used_bytes"] + s["reserved_bytes"] > s["budget_bytes"]
            for s in result["scopes"].values()
        )
        or total > settings.storage_total_bytes - settings.storage_headroom_bytes
    )
    result["unfinished_operations"] = [
        r.id
        for r in db.scalars(select(StorageReservation).where(StorageReservation.scope == "lock"))
    ]
    return result


def report(db: Session, scope: str, size: int) -> None:
    row = db.get(StorageUsage, scope)
    if row:
        row.size_bytes, row.measured_at = size, now()
    else:
        db.add(StorageUsage(scope=scope, size_bytes=size, measured_at=now()))


def reserve(
    db: Session, settings: Settings, identifier: str, scope: str, size: int, temporary: bool = False
) -> dict[str, Any]:
    if not settings.storage_enabled:
        raise HTTPException(503, "Storage budgets are not enabled")
    old = db.get(StorageReservation, identifier)
    if old:
        if old.scope != scope or old.size_bytes != size or old.temporary != temporary:
            raise HTTPException(409, "Reservation identity differs")
    state = usage(db, settings)
    if any(s["stale"] for s in state["scopes"].values()):
        raise HTTPException(
            503, "Storage measurement is missing or stale; reconcile before uploading"
        )
    selected = state["scopes"][scope]
    if temporary and scope != "recovery":
        raise HTTPException(422, "Only recovery uploads can reserve temporary headroom")
    budget = selected["budget_bytes"] + (settings.storage_headroom_bytes if temporary else 0)
    total_limit = settings.storage_total_bytes - (
        0 if temporary else settings.storage_headroom_bytes
    )
    if (
        selected["used_bytes"] > selected["budget_bytes"]
        or selected["used_bytes"] + selected["reserved_bytes"] + (0 if old else size) > budget
        or state["accounted_bytes"] + (0 if old else size) > total_limit
    ):
        raise HTTPException(507, "Storage budget exhausted; protected data was preserved")
    if not old:
        db.add(StorageReservation(id=identifier, scope=scope, size_bytes=size, temporary=temporary))
    return {"id": identifier, "scope": scope, "size_bytes": size}


@contextmanager
def receipt_lock(sessions: sessionmaker[Session]) -> Iterator[None]:
    """A durable lease is intentionally not expired automatically after an uncertain upload."""
    with sessions() as db:
        db.add(StorageReservation(id="receipt-io", scope="lock", size_bytes=0))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409, "Receipt operation already running; inspect unfinished operations"
            ) from None
    try:
        yield
    finally:
        with sessions() as db:
            row = db.get(StorageReservation, "receipt-io")
            if row:
                db.delete(row)
                db.commit()


def reconcile(sessions: sessionmaker[Session], store: ObjectStorage | None) -> dict[str, Any]:
    inventory: dict[str, Any] = (
        store.inventory() if store else {"size_bytes": 0, "versions": [], "uploads": []}
    )
    with sessions() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        report(db, "receipts", inventory["size_bytes"])
        db.commit()
    return inventory


def receipt_view(row: Receipt) -> dict[str, Any]:
    return {
        "id": row.id,
        "payment_id": row.payment_id,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "media_type": row.media_type,
        "state": row.state,
        "keep": row.keep,
        "created_at": timestamp(row.created_at),
        "deleted_at": timestamp(row.deleted_at),
        "deletion_reason": row.deletion_reason,
    }


def validate_image(data: bytes, media_type: str, maximum: int) -> None:
    if not data or len(data) > maximum or media_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(422, "Use a JPEG or PNG within the receipt size limit")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format != {"image/jpeg": "JPEG", "image/png": "PNG"}[media_type]
                or image.width * image.height > 25_000_000
                or getattr(image, "is_animated", False)
            ):
                raise ValueError("Unsupported image")
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, "Invalid or oversized image content") from None


def cleanup(
    sessions: sessionmaker[Session],
    settings: Settings,
    store: ObjectStorage,
    *,
    execute: bool,
    pressure: bool = False,
    incoming: int = 0,
) -> dict[str, Any]:
    inventory = reconcile(sessions, store)
    deadline = now() - timedelta(days=settings.receipt_retention_days)
    protected = now() - timedelta(days=settings.receipt_protect_days)
    target = int(settings.storage_receipt_bytes * 0.8)
    size = inventory["size_bytes"]
    candidates = []
    with sessions() as db:
        rows = list(
            db.scalars(
                select(Receipt)
                .where(
                    Receipt.state.in_(["available", "failed", "uploading", "deleting"]),
                    Receipt.keep.is_(False),
                )
                .order_by(Receipt.created_at, Receipt.id)
            )
        )
        for row in rows:
            age = utc(row.created_at)
            abandoned = row.state != "available" and age < now() - timedelta(days=1)
            if age >= protected and not abandoned:
                continue
            expired = age < deadline or abandoned or row.state == "deleting"
            if not expired and not (pressure and size + incoming > target):
                continue
            versions = [v for v in inventory["versions"] if v["key"] == row.object_key]
            reclaimed = sum(v["size"] for v in versions)
            candidates.append(
                {
                    "id": row.id,
                    "size_bytes": reclaimed,
                    "reason": "expired"
                    if age < deadline
                    else "abandoned"
                    if abandoned
                    else "capacity",
                }
            )
            size -= reclaimed
    if execute:
        for item in candidates:
            with sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                row = require(db, Receipt, item["id"])
                if row.keep:
                    raise HTTPException(409, "Receipt protection changed; preview cleanup again")
                row.state = "deleting"
                object_key = row.object_key
                db.commit()
            for version in inventory["versions"]:
                if version["key"] == object_key:
                    store.delete(object_key, version["version"])
            # A fresh listing proves object-version deletion before space is credited.
            remaining = store.inventory()
            if any(v["key"] == object_key for v in remaining["versions"]):
                raise HTTPException(503, "Receipt deletion not yet verified")
            with sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                row = require(db, Receipt, item["id"])
                row.state, row.deleted_at, row.deletion_reason = "expired", now(), item["reason"]
                reservation = db.get(StorageReservation, "receipt:" + row.id)
                if reservation:
                    db.delete(reservation)
                report(db, "receipts", remaining["size_bytes"])
                db.commit()
        for upload in inventory["uploads"]:
            if upload["key"].startswith("receipts/") and utc(
                upload["started_at"]
            ) < now() - timedelta(days=1):
                store.abort(upload["key"], upload["id"])
        reconcile(sessions, store)
    return {
        "execute": execute,
        "pressure": pressure,
        "candidates": candidates,
        "projected_bytes": size,
        "before_bytes": inventory["size_bytes"],
    }


def upload(
    sessions: sessionmaker[Session],
    settings: Settings,
    store: ObjectStorage,
    payment_id: str,
    key: str,
    data: bytes,
    media_type: str,
) -> dict[str, Any]:
    validate_image(data, media_type, settings.receipt_max_bytes)
    with sessions() as db:
        require(db, Payment, payment_id)
    digest = hashlib.sha256(data).hexdigest()
    identifier = str(uuid4())
    # Stable identifier binds the payment, retry key and bytes, without retaining the image in SQL.
    object_id = hashlib.sha256((payment_id + ":" + key).encode()).hexdigest()
    with receipt_lock(sessions):
        with sessions() as db:
            old = db.scalar(select(Receipt).where(Receipt.object_key == "receipts/" + object_id))
            if old:
                if old.sha256 != digest or old.media_type != media_type:
                    raise HTTPException(409, "Receipt retry differs from original upload")
                if old.state == "available":
                    return receipt_view(old)
                if old.state not in {"failed", "uploading"}:
                    raise HTTPException(409, "Receipt was removed; use a new upload identity")
                identifier = old.id
        # Reconcile an uncertain put without creating another stored version.
        inventory = reconcile(sessions, store)
        existing = [
            v
            for v in inventory["versions"]
            if v["key"] == "receipts/" + object_id and v["size"] > 0
        ]
        if existing:
            if (
                len(existing) != 1
                or hashlib.sha256(
                    store.get(
                        existing[0]["key"], existing[0]["version"], settings.receipt_max_bytes
                    )
                ).hexdigest()
                != digest
            ):
                raise HTTPException(409, "Uncertain upload requires administrator reconciliation")
            with sessions() as db:
                row = db.get(Receipt, identifier)
                if row is None:
                    raise HTTPException(
                        409, "Object lacks receipt metadata; inspect before retrying"
                    )
                row.version_id, row.state = existing[0]["version"], "available"
                reservation = db.get(StorageReservation, "receipt:" + identifier)
                if reservation:
                    db.delete(reservation)
                db.commit()
                return receipt_view(row)
        with sessions() as db:
            state = usage(db, settings)
        if state["scopes"]["receipts"]["used_bytes"] + len(data) > settings.storage_receipt_bytes:
            if not settings.storage_cleanup_enabled:
                raise HTTPException(507, "Receipt budget full; automatic cleanup is not enabled")
            cleanup(sessions, settings, store, execute=True, pressure=True, incoming=len(data))
        with sessions() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            require(db, Payment, payment_id)
            reserve(db, settings, "receipt:" + identifier, "receipts", len(data))
            row = db.get(Receipt, identifier)
            if row is None:
                row = Receipt(
                    id=identifier,
                    payment_id=payment_id,
                    object_key="receipts/" + object_id,
                    sha256=digest,
                    size_bytes=len(data),
                    media_type=media_type,
                    state="uploading",
                )
                db.add(row)
            else:
                row.state = "uploading"
            db.commit()
        try:
            version = store.put("receipts/" + object_id, data, media_type)
            if (
                hashlib.sha256(
                    store.get("receipts/" + object_id, version, settings.receipt_max_bytes)
                ).hexdigest()
                != digest
            ):
                raise ValueError("Stored receipt checksum differs")
            reconcile(sessions, store)
            with sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                row = require(db, Receipt, identifier)
                row.version_id, row.state = version, "available"
                db.delete(require(db, StorageReservation, "receipt:" + identifier))
                db.commit()
                return receipt_view(row)
        except Exception:
            with sessions() as db:
                row = require(db, Receipt, identifier)
                row.state = "failed"
                db.commit()
            # Keep the reservation until a retry/cleanup proves whether the put succeeded.
            raise HTTPException(503, "Receipt upload incomplete; retry with the same key") from None


def restore(
    sessions: sessionmaker[Session],
    settings: Settings,
    store: ObjectStorage,
    identifier: str,
    data: bytes,
    media_type: str,
) -> dict[str, Any]:
    """Rehydrate a verified recovery object and update only its storage version reference."""
    validate_image(data, media_type, settings.receipt_max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    reservation_id = "restore:" + identifier
    with receipt_lock(sessions):
        with sessions() as db:
            row = require(db, Receipt, identifier)
            if row.sha256 != digest or row.size_bytes != len(data) or row.media_type != media_type:
                raise HTTPException(409, "Recovery object differs from recorded receipt")
            if row.state == "expired":
                raise HTTPException(409, "Expired receipt must not be resurrected")
            object_key = row.object_key
        inventory = reconcile(sessions, store)
        matching = [
            v for v in inventory["versions"] if v["key"] == object_key and v["size"] == len(data)
        ]
        version = None
        for item in matching:
            if (
                hashlib.sha256(
                    store.get(object_key, item["version"], settings.receipt_max_bytes)
                ).hexdigest()
                == digest
            ):
                version = item["version"]
                break
        if version is None:
            with sessions() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                reserve(db, settings, reservation_id, "receipts", len(data))
                db.commit()
            try:
                version = store.put(object_key, data, media_type)
                if (
                    hashlib.sha256(
                        store.get(object_key, version, settings.receipt_max_bytes)
                    ).hexdigest()
                    != digest
                ):
                    raise ValueError("Restored object verification failed")
            except Exception:
                raise HTTPException(
                    503, "Receipt restoration incomplete; reconcile before retrying"
                ) from None
            reconcile(sessions, store)
        with sessions() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            row = require(db, Receipt, identifier)
            row.version_id, row.state = version, "available"
            reserved = db.get(StorageReservation, reservation_id)
            if reserved:
                db.delete(reserved)
            db.commit()
            return receipt_view(row)
