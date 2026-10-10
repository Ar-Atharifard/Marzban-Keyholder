"""Marzban controls enabled profiles without per-customer policy edits."""

import base64
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import GRPC, LINK
from tests.test_api import HEADERS, create


def test_marzban_authority_tracks_upstream_and_preserves_url(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    token = str(result["token"])
    cid = customer["id"]
    client.patch(
        "/admin/customers/" + str(cid),
        headers=HEADERS,
        json={"policy": {"profiles": ["xhttp_reality"]}},
    )
    app.state.settings.profile_source = "marzban"

    class ChangingBackend:
        links = [LINK, GRPC]

        async def configurations(self, username: str) -> list[str]:
            return self.links

    upstream = ChangingBackend()
    app.state.backends = {"marzban-default": upstream}
    url = "/s/" + token
    response = client.get(url)
    assert response.status_code == 200
    assert len(base64.b64decode(response.text).decode().splitlines()) == 2
    upstream.links = [GRPC]
    response = client.get(url)
    assert response.status_code == 200
    assert len(base64.b64decode(response.text).decode().splitlines()) == 1
    assert client.get("/admin/customers/" + str(cid), headers=HEADERS).json()["id"] == cid
    assert client.get(url + "?format=xray").status_code == 200


def test_policy_mode_remains_compatible(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    assert app.state.settings.profile_source == "policy"
    result = create(client)
    customer = result["customer"]
    assert isinstance(customer, dict)
    client.patch(
        "/admin/customers/" + str(customer["id"]),
        headers=HEADERS,
        json={"policy": {"profiles": []}},
    )
    assert client.get("/s/" + str(result["token"])).status_code == 503
