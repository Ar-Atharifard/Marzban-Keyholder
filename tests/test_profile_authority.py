"""Marzban controls enabled profiles without per-customer policy edits."""

import base64
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import GRPC, HEADERS, LINK, create


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


def test_full_catalog_ech_is_scoped_to_backend_and_account(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    result = create(client)
    app.state.settings.profile_source = "marzban"
    app.state.settings.allowed_cdn_hosts = ("titan.example",)
    app.state.settings.cdn_ech_config = "cloudflare-ech.com+https://1.1.1.1/dns-query"
    app.state.settings.cdn_tls_compatibility = True
    app.state.settings.cdn_ech_kinds = ()
    link = GRPC.replace("sni=tls.example", "sni=titan.example")

    class Backend:
        async def configurations(self, username: str) -> list[str]:
            return [link]

    app.state.backends = {"marzban-default": Backend()}
    url = "/s/" + str(result["token"])
    assert len(base64.b64decode(client.get(url).content).splitlines()) == 1
    name = result["customer"]["mapping"]["upstream_username"]  # type: ignore[index]
    app.state.settings.cdn_ech_full_catalog = ("another-backend/" + str(name),)
    assert len(base64.b64decode(client.get(url).content).splitlines()) == 1
    app.state.settings.cdn_ech_full_catalog = ("marzban-default/" + str(name),)
    assert len(base64.b64decode(client.get(url).content).splitlines()) == 2
