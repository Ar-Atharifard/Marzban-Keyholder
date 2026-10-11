import base64
import json
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from keyholder.policies import SUPPORTED_KINDS
from keyholder.rendering.profiles import apply_cdn_ech, generate_profiles, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from keyholder.schemas import Policy
from tests.conftest import UUID
from tests.test_api import create
from tests.test_native_ech import ECH, HOSTS

LINK = (
    "trojan://synthetic-password@titan.example:443?type=xhttp&security=tls"
    "&sni=titan.example&host=titan.example&path=%2Fstream&mode=stream-up"
    "&alpn=h2%2Chttp%2F1.1&extra=discard&flow=xtls-rprx-vision#Trojan-stream"
)


def test_streaming_trojan_roundtrip_preserves_security_and_strips_extra() -> None:
    policy = Policy.model_validate({"profiles": list(SUPPORTED_KINDS)})
    profiles = generate_profiles([LINK], policy)
    assert len(profiles) == 1 and profiles[0].kind == "trojan_xhttp_cdn"
    enabled = apply_cdn_ech(profiles, ECH, HOSTS)
    uri = base64.b64decode(URIRenderer().render(enabled)).decode().strip()
    query = parse_qs(urlsplit(uri).query)
    assert query["mode"] == ["stream-up"] and query["ech"] == [ECH]
    assert "extra" not in query and "flow" not in query and "encryption" not in query
    again = normalize(uri)
    assert again is not None and again.password == profiles[0].password
    outbound = json.loads(XrayRenderer().render(enabled))[0]["outbounds"][0]
    assert outbound["protocol"] == "trojan" and outbound["mux"]["enabled"] is False
    assert outbound["settings"]["servers"][0]["password"] == "synthetic-password"
    stream = outbound["streamSettings"]
    assert stream["xhttpSettings"] == {
        "host": "titan.example",
        "path": "/stream",
        "mode": "stream-up",
    }
    assert stream["tlsSettings"]["allowInsecure"] is False
    assert stream["tlsSettings"]["alpn"] == ["h2", "http/1.1"]


@pytest.mark.parametrize("replacement", ["192.0.2.1", "[2001:db8::1]"])
def test_streaming_trojan_never_allows_literal_origin_addresses(replacement: str) -> None:
    assert normalize(LINK.replace("titan.example:443", replacement + ":443")) is None


def test_legacy_policy_does_not_silently_grant_streaming_trojan() -> None:
    assert generate_profiles([LINK], Policy()) == []


def test_streaming_modes_follow_panel_without_changing_subscription_url(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    registration = create(client)
    path = "/s/" + str(registration["token"])

    class Backend:
        links = [LINK, LINK.replace("trojan://synthetic-password", "vless://" + UUID)]

        async def configurations(self, username: str) -> list[str]:
            return self.links

    backend = Backend()
    app.state.backends = {"marzban-default": backend}
    app.state.settings.profile_source = "marzban"
    app.state.settings.allowed_cdn_hosts = HOSTS
    app.state.settings.cdn_ech_config = ECH
    response = client.get(path)
    assert response.status_code == 200
    assert len(base64.b64decode(response.text).decode().splitlines()) == 2
    backend.links = [backend.links[1]]
    response = client.get(path)
    assert response.status_code == 200
    assert len(base64.b64decode(response.text).decode().splitlines()) == 1
