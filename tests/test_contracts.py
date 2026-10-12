"""Frozen synthetic contracts: changes require explicit compatibility review."""

import json
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.main import create_app
from keyholder.rendering.profiles import generate_profiles
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from keyholder.schemas import Policy
from scripts.backup_database import backup_database
from tests.conftest import ADMIN_KEY, ALL
from tests.test_api import HEADERS, create

CONTRACTS = Path(__file__).parent / "contracts"


def test_existing_api_contract_is_unchanged(client: TestClient) -> None:
    schema = cast(FastAPI, client.app).openapi()
    baseline = json.loads((CONTRACTS / "api-v1.json").read_text())
    for path, operations in baseline["paths"].items():
        for method, operation in operations.items():
            actual_operation = json.loads(json.dumps(schema["paths"][path][method]))
            if path == "/s/{token}" and method == "get":
                parameter = next(p for p in actual_operation["parameters"] if p["name"] == "format")
                choices = parameter["schema"]["anyOf"][0]["enum"]
                assert choices == ["uri", "xray", "info"]
                # Explicit additive usage view: existing formats/defaults remain frozen.
                parameter["schema"]["anyOf"][0]["enum"] = ["uri", "xray"]
            assert actual_operation == operation
    for name, model in baseline["schemas"].items():
        actual = json.loads(json.dumps(schema["components"]["schemas"][name]))
        if name == "Policy":
            # Reviewed additive expansion only: existing defaults/values stay frozen.
            old = model["properties"]["profiles"]
            new = actual["properties"]["profiles"]
            assert new["items"]["enum"] == old["items"]["enum"] + [
                "ws_tls_cdn",
                "xhttp_tls_cdn",
                "trojan_grpc_cdn",
                "vmess_httpupgrade_cdn",
                "trojan_reality_ipv6",
                "trojan_xhttp_cdn",
            ]
            assert new["maxItems"] == 11 and old["maxItems"] == 5
            new["items"]["enum"] = old["items"]["enum"]
            new["maxItems"] = old["maxItems"]
        assert actual == model


def test_frozen_subscription_formats() -> None:
    profiles = generate_profiles(ALL, Policy())
    assert URIRenderer().render(profiles) == (CONTRACTS / "subscription-v1.uri").read_text().strip()
    assert json.loads(XrayRenderer().render(profiles)) == json.loads(
        (CONTRACTS / "subscription-v1.xray.json").read_text()
    )


def test_original_subscription_survives_management_restart_and_database_move(
    client: TestClient, tmp_path: Path
) -> None:
    app = cast(FastAPI, client.app)
    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    token = str(result["token"])
    url = str(result["subscription_url"])
    assert url == f"{app.state.settings.public_base_url}/s/{token}"
    path = "/s/" + token
    assert client.get(path).status_code == 200
    assert (
        client.patch(
            f"/admin/customers/{cid}",
            headers=HEADERS,
            json={"name": "Renamed", "policy": {"profiles": ["xhttp_reality"]}},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/admin/customers/{cid}/mapping",
            headers=HEADERS,
            json={"upstream_username": "replacement"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/admin/customers/{cid}", headers=HEADERS, json={"status": "disabled"}
        ).status_code
        == 200
    )
    assert client.get(path).status_code == 404
    assert (
        client.patch(
            f"/admin/customers/{cid}", headers=HEADERS, json={"status": "active"}
        ).status_code
        == 200
    )
    expected = client.get(path)
    assert expected.status_code == 200
    source = Path(app.state.engine.url.database)
    relocated = tmp_path / "relocated.db"
    backup_database(source, relocated)
    replacement = create_app(
        Settings(
            admin_key=SecretStr(ADMIN_KEY),
            database_url=f"sqlite:///{relocated}",
            public_base_url=app.state.settings.public_base_url,
        )
    )
    with TestClient(replacement) as restarted:
        replacement.state.backends = app.state.backends
        response = restarted.get(path)
        assert response.status_code == 200 and response.content == expected.content
        assert response.headers["content-type"].startswith("text/plain")
        assert restarted.get(path + "?format=xray").status_code == 200
        assert (
            restarted.get(path, headers={"User-Agent": "Keyholder-Xray"})
            .headers["content-type"]
            .startswith("application/json")
        )
        assert restarted.get(path + "?format=unknown").status_code == 422


def test_preexisting_v1_token_hash_remains_usable(client: TestClient) -> None:
    from keyholder.models import Customer
    from keyholder.security import hash_token, valid_token

    # Fixed synthetic persisted digest: independent of the current generator/hash.
    token = "A" * 43
    digest = "0f007385b6f9d4b7eeb2748605afe1a984a0a3bfa3f014d09e2a784ce9e5cd1a"
    assert valid_token(token) and hash_token(token) == digest
    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    app = cast(FastAPI, client.app)
    with app.state.sessions() as db:
        row = db.get(Customer, customer["id"])
        assert row is not None
        row.token_hash = digest
        db.commit()
    assert client.get("/s/" + token).status_code == 200
    assert client.get("/s/" + token + "?format=xray").status_code == 200
