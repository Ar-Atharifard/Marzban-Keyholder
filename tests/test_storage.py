import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from keyholder.billing_models import Receipt, StorageReservation, StorageUsage
from keyholder.models import now
from keyholder.object_storage import ObjectStorage
from tests.support import ADMIN_KEY

HEADERS = {"Authorization": "Bearer " + ADMIN_KEY}


class FakeStore(ObjectStorage):
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail_after_put = False
        self.fail_delete = False
        self.puts = 0

    def inventory(self) -> dict[str, Any]:
        return {
            "size_bytes": sum(len(v) for v in self.objects.values()),
            "versions": [
                {"key": k, "version": v, "size": len(data)} for (k, v), data in self.objects.items()
            ],
            "uploads": [],
        }

    def put(self, key: str, data: bytes, media_type: str) -> str:
        version = str(uuid4())
        self.objects[key, version] = data
        self.puts += 1
        if self.fail_after_put:
            raise OSError("Synthetic uncertain put")
        return version

    def get(self, key: str, version: str, maximum: int) -> bytes:
        return self.objects[key, version]

    def delete(self, key: str, version: str) -> None:
        if self.fail_delete:
            raise OSError("Synthetic deletion failure")
        self.objects.pop((key, version), None)


def image() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, "PNG")
    return stream.getvalue()


def post(client: TestClient, path: str, body: dict[str, Any]) -> Any:
    return client.post(
        "/admin/" + path, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid4())}
    )


@pytest.fixture
def storage_client(client: TestClient) -> tuple[TestClient, FakeStore, str]:
    app = cast(FastAPI, client.app)
    app.state.settings.storage_enabled = True
    app.state.settings.storage_cleanup_enabled = True
    app.state.settings.rate_limit_per_minute = 1000
    app.state.limiter.limit = 1000
    store = FakeStore()
    app.state.receipt_store = store
    cid = client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Alice", "upstream_username": "alice"}
    ).json()["customer"]["id"]
    pid = post(
        client, "payments", {"customer_id": cid, "amount": "1000", "receiving_account": "personal"}
    ).json()["id"]
    client.put("/admin/storage/usage/recovery", json={"size_bytes": 0}, headers=HEADERS)
    assert post(client, "storage/reconcile", {}).status_code == 200
    return client, store, pid


def upload(client: TestClient, pid: str, key: str | None = None) -> Any:
    return client.post(
        f"/admin/payments/{pid}/receipts",
        content=image(),
        headers={**HEADERS, "Idempotency-Key": key or str(uuid4()), "Content-Type": "image/png"},
    )


def test_private_upload_retry_and_content_validation(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, store, pid = storage_client
    key = str(uuid4())
    first = upload(client, pid, key)
    assert first.status_code == 201, first.text
    row = first.json()
    assert upload(client, pid, key).json() == row
    assert store.puts == 1
    assert client.get(f"/admin/receipts/{row['id']}/content", headers=HEADERS).content == image()
    assert client.get(f"/admin/receipts/{row['id']}/content").status_code == 401
    assert (
        client.post(
            f"/admin/payments/{pid}/receipts",
            content=b"not an image",
            headers={**HEADERS, "Idempotency-Key": str(uuid4()), "Content-Type": "image/png"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/admin/payments/{pid}/receipts",
            content=image(),
            headers={**HEADERS, "Idempotency-Key": key, "Content-Type": "image/jpeg"},
        ).status_code
        == 422
    )
    payment = client.get(f"/admin/payments/{pid}", headers=HEADERS).json()
    assert payment["status"] == "pending"


def test_uncertain_put_recovers_same_version(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, store, pid = storage_client
    key = str(uuid4())
    store.fail_after_put = True
    assert upload(client, pid, key).status_code == 503
    state = client.get("/admin/storage", headers=HEADERS).json()
    assert state["scopes"]["receipts"]["reserved_bytes"] == len(image())
    store.fail_after_put = False
    assert upload(client, pid, key).status_code == 201
    assert store.puts == 1
    assert (
        client.get("/admin/storage", headers=HEADERS).json()["scopes"]["receipts"]["reserved_bytes"]
        == 0
    )


def test_expiry_protection_and_tombstone(storage_client: tuple[TestClient, FakeStore, str]) -> None:
    client, store, pid = storage_client
    ids = [upload(client, pid).json()["id"] for _ in range(3)]
    app = cast(FastAPI, client.app)
    with app.state.sessions() as db:
        for row in db.scalars(select(Receipt)):
            if row.id != ids[2]:
                row.created_at = now() - timedelta(days=181)
        db.commit()
    assert (
        post(
            client, f"receipts/{ids[1]}/protection", {"keep": True, "reason": "Open dispute"}
        ).status_code
        == 200
    )
    preview = post(client, "storage/receipts/cleanup", {}).json()
    assert [r["id"] for r in preview["candidates"]] == [ids[0]]
    assert len(store.objects) == 3
    assert post(client, "storage/receipts/cleanup", {"execute": True}).status_code == 200
    assert len(store.objects) == 2
    assert client.get(f"/admin/receipts/{ids[0]}/content", headers=HEADERS).status_code == 410
    rows = client.get(f"/admin/payments/{pid}/receipts", headers=HEADERS).json()
    expired = next(r for r in rows if r["id"] == ids[0])
    assert (
        expired["state"] == "expired"
        and expired["sha256"]
        and expired["deletion_reason"] == "expired"
    )
    assert client.get(f"/admin/payments/{pid}", headers=HEADERS).status_code == 200


def test_capacity_versions_and_protected_upload_refusal(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, store, pid = storage_client
    app = cast(FastAPI, client.app)
    app.state.settings.storage_receipt_bytes = len(image()) * 2
    one = upload(client, pid).json()
    ((key, _), data) = next(iter(store.objects.items()))
    store.objects[key, "hidden-old-version"] = data
    assert upload(client, pid).status_code == 507
    # A 31-day-old image can be removed under pressure, including all its versions.
    with app.state.sessions() as db:
        row = db.get(Receipt, one["id"])
        row.created_at = now() - timedelta(days=31)
        db.commit()
    assert upload(client, pid).status_code == 201
    assert len(store.objects) == 1


def test_failed_deletion_never_credits_space(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, store, pid = storage_client
    rid = upload(client, pid).json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.sessions() as db:
        db.get(Receipt, rid).created_at = now() - timedelta(days=200)
        db.commit()
    store.fail_delete = True
    assert post(client, "storage/receipts/cleanup", {"execute": True}).status_code == 500
    assert len(store.objects) == 1
    assert client.get("/admin/storage", headers=HEADERS).json()["scopes"]["receipts"][
        "used_bytes"
    ] == len(image())
    store.fail_delete = False
    assert post(client, "storage/receipts/cleanup", {"execute": True}).status_code == 200


def test_stale_measurements_and_atomic_admission(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, _, _ = storage_client
    app = cast(FastAPI, client.app)
    app.state.settings.storage_recovery_bytes = 1000
    with app.state.sessions() as db:
        db.get(StorageUsage, "recovery").measured_at = now() - timedelta(days=2)
        db.commit()
    assert (
        post(
            client, "storage/reservations/" + str(uuid4()), {"scope": "recovery", "size_bytes": 600}
        ).status_code
        == 503
    )
    client.put("/admin/storage/usage/recovery", json={"size_bytes": 0}, headers=HEADERS)

    def reserve(_: int) -> int:
        return int(
            post(
                client,
                "storage/reservations/" + str(uuid4()),
                {"scope": "recovery", "size_bytes": 600},
            ).status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [200, 507]
    with app.state.sessions() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(StorageReservation).where(StorageReservation.scope == "recovery")
                    )
                )
            )
            == 1
        )


def test_restoration_updates_version_preserving_identity(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, store, pid = storage_client
    row = upload(client, pid).json()
    store.objects.clear()
    post(client, "storage/reconcile", {})
    result = client.post(
        f"/admin/receipts/{row['id']}/restore",
        content=image(),
        headers={**HEADERS, "Idempotency-Key": str(uuid4()), "Content-Type": "image/png"},
    )
    assert result.status_code == 200, result.text
    assert result.json() == row
    assert client.get(f"/admin/receipts/{row['id']}/content", headers=HEADERS).content == image()


def test_capture_and_restore_receipt_bundle(
    storage_client: tuple[TestClient, FakeStore, str],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import recovery
    from scripts.storage_budget import Budget

    client, store, pid = storage_client
    row = upload(client, pid).json()
    source = tmp_path / "source.txt"
    source.write_text("synthetic configuration")
    bundle = tmp_path / "bundle"
    recovery.capture({"service_id": "test", "files": {"rootfs/config.txt": str(source)}}, bundle)
    budget = Budget.__new__(Budget)
    budget.work = tmp_path / "cache-work"
    budget.work.mkdir(mode=0o700)

    def api(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        response = client.request(
            method,
            "/admin" + path,
            json=body if kwargs.get("raw") is None else None,
            content=kwargs.get("raw"),
            headers={
                **HEADERS,
                "Idempotency-Key": str(uuid4()),
                "Content-Type": kwargs.get("media_type", "application/json"),
            },
        )
        assert response.status_code < 400, response.text
        return response.content if path.endswith("/content") else response.json()

    monkeypatch.setattr(budget, "api", api)
    monkeypatch.setattr(budget, "measure", lambda: {})
    budget.capture_receipts(bundle)
    # A second capture uses only the verified local cache, without fetching image bytes.
    second = tmp_path / "second-bundle"
    recovery.capture({"service_id": "test", "files": {"rootfs/config.txt": str(source)}}, second)
    original_api = budget.api

    def cached_api(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        assert not path.endswith("/content"), "Unchanged image should not be downloaded again"
        return original_api(method, path, *args, **kwargs)

    monkeypatch.setattr(budget, "api", cached_api)
    budget.capture_receipts(second)
    recovery.verify(second)
    monkeypatch.setattr(budget, "api", original_api)
    manifest = recovery.verify(bundle)
    assert manifest["receipt_objects"][0]["id"] == row["id"]
    store.objects.clear()
    post(client, "storage/reconcile", {})
    assert budget.restore_receipts(bundle, manifest) == 1
    assert client.get(f"/admin/receipts/{row['id']}/content", headers=HEADERS).content == image()


def test_recovery_can_temporarily_use_headroom_but_not_bypass_total(
    storage_client: tuple[TestClient, FakeStore, str],
) -> None:
    client, _, _ = storage_client
    app = cast(FastAPI, client.app)
    app.state.settings.storage_total_bytes = 2000
    app.state.settings.storage_receipt_bytes = 500
    app.state.settings.storage_recovery_bytes = 1000
    app.state.settings.storage_headroom_bytes = 500
    client.put("/admin/storage/usage/recovery", json={"size_bytes": 900}, headers=HEADERS)
    assert (
        post(
            client, "storage/reservations/" + str(uuid4()), {"scope": "recovery", "size_bytes": 400}
        ).status_code
        == 507
    )
    assert (
        post(
            client,
            "storage/reservations/" + str(uuid4()),
            {"scope": "recovery", "size_bytes": 400, "temporary": True},
        ).status_code
        == 200
    )
    assert (
        post(
            client,
            "storage/reservations/" + str(uuid4()),
            {"scope": "recovery", "size_bytes": 400, "temporary": True},
        ).status_code
        == 507
    )
    assert (
        post(
            client,
            "storage/reservations/" + str(uuid4()),
            {"scope": "receipts", "size_bytes": 1, "temporary": True},
        ).status_code
        == 422
    )
