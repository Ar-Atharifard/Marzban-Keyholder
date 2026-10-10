import asyncio
import base64
import json
import logging
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from keyholder.backends.base import UpstreamError
from keyholder.models import Customer
from tests.conftest import ADMIN_KEY, ALL, KINDS

HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}


def test_slow_upstream_does_not_exhaust_database_pool(client: TestClient) -> None:
    token = str(create(client)["token"])
    app = cast(FastAPI, client.app)
    engine = create_engine(
        app.state.engine.url,
        connect_args={"check_same_thread": False},
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.05,
    )
    original_sessions = app.state.sessions
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)

    async def exercise() -> None:
        entered = 0
        release = asyncio.Event()
        both_entered = asyncio.Event()

        class SlowBackend:
            async def configurations(self, username: str) -> list[str]:
                nonlocal entered
                entered += 1
                if entered == 2:
                    both_entered.set()
                await release.wait()
                return ALL

        app.state.backends = {"marzban-default": SlowBackend()}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            requests = [asyncio.create_task(api.get(f"/s/{token}")) for _ in range(2)]
            try:
                await asyncio.wait_for(both_entered.wait(), timeout=1)
                assert (await api.get("/health")).status_code == 200
            finally:
                release.set()
                responses = await asyncio.gather(*requests)
            assert [response.status_code for response in responses] == [200, 200]

    try:
        asyncio.run(exercise())
    finally:
        app.state.sessions = original_sessions
        engine.dispose()


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
    assert client.get("/admin/settings/ech", headers=HEADERS).status_code == 404


def test_rate_limit(client: TestClient) -> None:
    cast(FastAPI, client.app).state.limiter.limit = 1
    assert client.get("/s/invalid").status_code == 404
    assert client.get("/s/invalid").status_code == 429


def test_subscription_limits_are_per_token_and_ignore_forwarded_ips(
    client: TestClient, caplog: object
) -> None:
    from keyholder.security import hash_token

    first = str(create(client)["token"])
    second = client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Bob", "upstream_username": "bobby"}
    ).json()["token"]
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


@pytest.mark.parametrize("output", ["uri", "xray"])
def test_legacy_policy_delivers_reality_without_ech(client: TestClient, output: str) -> None:
    result = create(client)
    token = str(result["token"])
    legacy = {
        "profiles": ["xhttp_reality", "tcp_reality", "xhttp_cdn", "ws_cdn"],
        "ech_enabled": True,
        "include_base_cdn": False,
    }
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.scalar(select(Customer))
        assert row is not None
        row.policy = legacy
        db.commit()
    response = client.get(f"/s/{token}?format={output}")
    assert response.status_code == 200
    content = base64.b64decode(response.text).decode() if output == "uri" else response.text
    assert "extra" not in content and "ech" not in content
    view = client.get("/admin/customers", headers=HEADERS).json()[0]
    assert view["policy"] == {"profiles": ["xhttp_reality", "tcp_reality"]}
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.scalar(select(Customer))
        assert row is not None and row.policy == legacy  # GET never silently migrates data.


@pytest.mark.parametrize("policy", [{"profiles": ["ws_cdn"]}, {"profiles": []}, "invalid"])
def test_unsupported_stored_policy_fails_closed(client: TestClient, policy: object) -> None:
    result = create(client)
    with cast(FastAPI, client.app).state.sessions() as db:
        row = db.scalar(select(Customer))
        assert row is not None
        row.policy = policy
        db.commit()
    response = client.get(f"/s/{result['token']}")
    assert response.status_code == 503
    assert response.json() == {"detail": "No compatible subscription profiles"}


def test_ech_api_and_policy_are_retired(client: TestClient) -> None:
    for method in [client.get, client.put]:
        assert method("/admin/settings/ech", headers=HEADERS).status_code == 404
    response = client.post(
        "/admin/customers",
        headers=HEADERS,
        json={"name": "Fixture", "upstream_username": "alice", "policy": {"ech_enabled": True}},
    )
    assert response.status_code == 422


def test_upstream_total_deadline_is_sanitized(client: TestClient) -> None:
    class SlowBackend:
        async def configurations(self, username: str) -> list[str]:
            await asyncio.sleep(60)
            return []

    app = cast(FastAPI, client.app)
    token = create(client)["token"]
    app.state.settings.upstream_timeout = 0.01
    app.state.backends = {"marzban-default": SlowBackend()}
    response = client.get(f"/s/{token}")
    assert response.status_code == 502
    assert response.json() == {"detail": "Upstream unavailable"}


@pytest.mark.parametrize("output", ["uri", "xray"])
def test_all_current_families_through_subscription_api(client: TestClient, output: str) -> None:
    class CurrentBackend:
        async def configurations(self, username: str) -> list[str]:
            return ALL

    result = client.post(
        "/admin/customers",
        headers=HEADERS,
        json={"name": "Fixture", "upstream_username": "alice", "policy": {"profiles": KINDS}},
    ).json()
    cast(FastAPI, client.app).state.backends = {"marzban-default": CurrentBackend()}
    response = client.get(f"/s/{result['token']}?format={output}")
    assert response.status_code == 200
    if output == "uri":
        links = base64.b64decode(response.text).decode().splitlines()
        assert len(links) == 5 and sum(link.startswith("ss://") for link in links) == 1
    else:
        configs = json.loads(response.text)
        assert len(configs) == 5
        assert sum(c["outbounds"][0]["protocol"] == "shadowsocks" for c in configs) == 1
