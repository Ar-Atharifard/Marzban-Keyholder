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
            assert schema["paths"][path][method] == operation
    for name, model in baseline["schemas"].items():
        assert schema["components"]["schemas"][name] == model


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
