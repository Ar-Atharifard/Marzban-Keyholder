import base64
from concurrent.futures import ThreadPoolExecutor
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from keyholder.models import Customer, Registration
from tests.test_api import HEADERS, create


def test_registration_is_idempotent_encrypted_and_retrievable(client: TestClient) -> None:
    first = create(client)
    second = create(client)
    assert first == second
    cid = first["customer"]["id"]
    recovered = client.get(f"/admin/customers/{cid}/subscription", headers=HEADERS)
    assert recovered.status_code == 200 and recovered.json() == first
    assert client.get(f"/admin/customers/{cid}/subscription").status_code == 401
    app = cast(FastAPI, client.app)
    with app.state.sessions() as db:
        c = db.get(Customer, cid)
        assert c.token_encrypted and str(first["token"]) not in c.token_encrypted
        assert db.scalar(select(Registration)).customer_id == cid


def test_concurrent_registration_has_one_identity(client: TestClient) -> None:
    def register() -> dict:
        return client.post(
            "/admin/customers",
            headers=HEADERS,
            json={"name": "Concurrent", "upstream_username": "concurrent"},
        ).json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: register(), range(4)))
    assert len({r["customer"]["id"] for r in results}) == 1
    assert len({r["token"] for r in results}) == 1


def test_rotation_invalidates_old_link_and_remains_retrievable(client: TestClient) -> None:
    before = create(client)
    cid = before["customer"]["id"]
    after = client.post(f"/admin/customers/{cid}/rotate-token", headers=HEADERS).json()
    assert after["customer"]["id"] == cid and after["token"] != before["token"]
    assert client.get("/s/" + before["token"]).status_code == 404
    assert client.get("/s/" + after["token"]).status_code == 200
    assert client.get(f"/admin/customers/{cid}/subscription", headers=HEADERS).json() == after


def test_wrong_vault_key_never_mints_another_identity(client: TestClient) -> None:
    first = create(client)
    app = cast(FastAPI, client.app)
    app.state.settings.token_encryption_key = SecretStr(
        base64.urlsafe_b64encode(b"y" * 32).decode()
    )
    response = client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Again", "upstream_username": "alice"}
    )
    assert response.status_code == 503
    assert len(client.get("/admin/customers", headers=HEADERS).json()) == 1
    assert client.get("/s/" + first["token"]).status_code == 200


def test_mapping_cannot_claim_another_registered_user(client: TestClient) -> None:
    first = create(client)
    client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Bob", "upstream_username": "bobby"}
    )
    cid = first["customer"]["id"]
    response = client.put(
        f"/admin/customers/{cid}/mapping", headers=HEADERS, json={"upstream_username": "bobby"}
    )
    assert response.status_code == 409
    assert client.get("/s/" + first["token"]).status_code == 200
