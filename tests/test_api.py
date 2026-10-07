import logging
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from keyholder.backends.base import UpstreamError
from keyholder.models import Customer
from tests.conftest import ADMIN_KEY

HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}


def create(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Customer", "upstream_username": "alice"}
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def test_customer_lifecycle(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/admin/customers").status_code == 401
    result = create(client)
    token = str(result["token"])
    customer = result["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.scalar(select(Customer))
        assert row is not None and row.token_hash != token
    assert client.get(f"/s/{token}").status_code == 200
    assert client.get(f"/s/{token}?format=xray").status_code == 200
    assert (
        client.put(
            f"/admin/customers/{cid}/mapping", headers=HEADERS, json={"upstream_username": "bob"}
        ).status_code
        == 200
    )
    assert client.get(f"/s/{token}").status_code == 200
    assert (
        client.patch(
            f"/admin/customers/{cid}", headers=HEADERS, json={"status": "disabled"}
        ).status_code
        == 200
    )
    assert client.get(f"/s/{token}").status_code == 404
    client.patch(f"/admin/customers/{cid}", headers=HEADERS, json={"status": "active"})
    rotated = client.post(f"/admin/customers/{cid}/rotate-token", headers=HEADERS).json()["token"]
    assert client.get(f"/s/{token}").status_code == 404
    assert client.get(f"/s/{rotated}").status_code == 200
    revoked = client.patch(
        f"/admin/customers/{cid}", headers=HEADERS, json={"status": "revoked"}
    ).json()
    assert revoked["revoked_at"] is not None
    assert client.get(f"/s/{rotated}").status_code == 404
    assert (
        client.patch(
            f"/admin/customers/{cid}", headers=HEADERS, json={"status": "active"}
        ).status_code
        == 409
    )
    assert client.post(f"/admin/customers/{cid}/rotate-token", headers=HEADERS).status_code == 409
    assert len(client.get("/admin/customers", headers=HEADERS).json()) == 1


def test_secrets_not_logged_or_echoed(client: TestClient, caplog: object) -> None:
    with caplog.at_level(logging.INFO, logger="keyholder"):  # type: ignore[attr-defined]
        result = create(client)
        token = str(result["token"])
        r = client.get(f"/s/{token}?format={token}")
        assert r.status_code == 422 and token not in r.text
        assert r.headers["cache-control"] == "no-store"
    logs = caplog.text  # type: ignore[attr-defined]
    assert token not in logs and ADMIN_KEY not in logs
    assert '"route": "/s/{token}"' in logs


def test_validation_and_upstream_errors(client: TestClient) -> None:
    assert (
        client.post(
            "/admin/customers",
            headers=HEADERS,
            json={"name": "x", "upstream_username": "../../evil"},
        ).status_code
        == 422
    )
    assert client.get("/s/invalid").status_code == 404

    class Broken:
        async def configurations(self, username: str) -> list[str]:
            raise UpstreamError("secret upstream body")

    token = create(client)["token"]
    cast(FastAPI, client.app).state.backends = {"marzban-default": Broken()}
    response = client.get(f"/s/{token}")
    assert response.status_code == 502 and "secret" not in response.text
    assert (
        client.put(
            "/admin/settings/ech", headers=HEADERS, json={"ech_config_list": "bad"}
        ).status_code
        == 422
    )


def test_rate_limit(client: TestClient) -> None:
    cast(FastAPI, client.app).state.limiter.limit = 1
    assert client.get("/s/invalid").status_code == 404
    assert client.get("/s/invalid").status_code == 429


def test_ech_application_data_updates_without_token_change(client: TestClient) -> None:
    import base64

    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    token = result["token"]
    client.patch(f"/admin/customers/{cid}", headers=HEADERS, json={"policy": {"ech_enabled": True}})
    assert client.get(f"/s/{token}?format=xray").status_code == 503
    for payload in [b"\x00\x04\xfe\x0d\x00\x00", b"\x00\x05\xfe\x0d\x00\x01\x01"]:
        ech = base64.b64encode(payload).decode()
        assert (
            client.put(
                "/admin/settings/ech", headers=HEADERS, json={"ech_config_list": ech}
            ).status_code
            == 200
        )
        assert client.get("/admin/settings/ech", headers=HEADERS).json()["ech_config_list"] == ech
        response = client.get(f"/s/{token}?format=xray")
        assert response.status_code == 200
        assert (
            response.json()[1]["outbounds"][0]["streamSettings"]["tlsSettings"]["echConfigList"]
            == ech
        )


def test_subscription_limits_are_per_token_and_ignore_forwarded_ips(
    client: TestClient, caplog: object
) -> None:
    from keyholder.security import hash_token

    first = str(create(client)["token"])
    second = str(create(client)["token"])
    limiter = cast(FastAPI, client.app).state.limiter
    limiter.windows.clear()
    limiter.limit = 1
    with caplog.at_level(logging.INFO, logger="keyholder"):  # type: ignore[attr-defined]
        assert client.get(f"/s/{first}", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 200
        # Query/format and forwarded-IP changes cannot evade the same token's limit.
        limited = client.get(f"/s/{first}?format=xray", headers={"X-Forwarded-For": "5.6.7.8"})
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"
        assert client.get(f"/s/{second}").status_code == 200
        assert client.get("/admin/customers", headers=HEADERS).status_code == 200
        assert (
            client.get(
                "/admin/customers", headers={**HEADERS, "X-Forwarded-For": "9.10.11.12"}
            ).status_code
            == 429
        )
    assert "subscription:" + hash_token(first) in limiter.windows
    assert "subscription:" + hash_token(second) in limiter.windows
    logs = caplog.text  # type: ignore[attr-defined]
    assert all(
        value not in logs for value in [first, second, hash_token(first), hash_token(second)]
    )
    assert client.get("/s/%C3%BC").status_code == 404


def test_revoked_mapping_and_rotation_leave_customer_unchanged(client: TestClient) -> None:
    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    client.patch(f"/admin/customers/{cid}", headers=HEADERS, json={"status": "revoked"})
    before = client.get(f"/admin/customers/{cid}", headers=HEADERS).json()
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.get(Customer, cid)
        assert row is not None
        digest_before = row.token_hash
    assert (
        client.put(
            f"/admin/customers/{cid}/mapping", headers=HEADERS, json={"upstream_username": "bob"}
        ).status_code
        == 409
    )
    assert client.post(f"/admin/customers/{cid}/rotate-token", headers=HEADERS).status_code == 409
    assert client.get(f"/admin/customers/{cid}", headers=HEADERS).json() == before
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.get(Customer, cid)
        assert row is not None and row.token_hash == digest_before


def test_mapping_and_rotation_update_timestamp(client: TestClient, monkeypatch: object) -> None:
    from datetime import UTC, datetime

    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    mapping_time = datetime(2030, 1, 1, tzinfo=UTC)
    rotation_time = datetime(2030, 1, 2, tzinfo=UTC)
    monkeypatch.setattr("keyholder.api.admin.now", lambda: mapping_time)  # type: ignore[attr-defined]
    mapped = client.put(
        f"/admin/customers/{cid}/mapping", headers=HEADERS, json={"upstream_username": "bob"}
    )
    assert mapped.status_code == 200
    assert datetime.fromisoformat(mapped.json()["updated_at"]) == mapping_time
    monkeypatch.setattr("keyholder.api.admin.now", lambda: rotation_time)  # type: ignore[attr-defined]
    rotated = client.post(f"/admin/customers/{cid}/rotate-token", headers=HEADERS)
    assert rotated.status_code == 200
    assert datetime.fromisoformat(rotated.json()["customer"]["updated_at"]) == rotation_time
    assert rotated.json()["token"] != result["token"]
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.get(Customer, cid)
        assert row is not None
        assert row.updated_at.replace(tzinfo=UTC) == rotation_time
