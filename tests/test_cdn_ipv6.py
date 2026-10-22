"""Cloudflare IPv6 alternatives retain strict CDN identity and stable subscription contracts."""

import base64
import json
from dataclasses import replace
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from keyholder.rendering.profiles import allowed_cdn, apply_cdn_ech, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from tests.support import CDN_HOSTS as HOSTS
from tests.support import ECH, GRPC, UUID, create, vmess

EDGE = "2a06:98c1:3121::7"


def variants() -> list[str]:
    grpc = (
        GRPC.replace("titan.example:443", f"[{EDGE}]:443")
        .replace("sni=tls.example", "sni=titan.example")
        .replace("authority=grpc.example", "authority=titan.example")
        .replace("#Titan", "#Titan-IPv6")
    )
    ws = grpc.replace("type=grpc", "type=ws").replace(
        "#Titan-IPv6", "&host=titan.example&path=%2Fws#Titan-IPv6"
    )
    xhttp = ws.replace("type=ws", "type=xhttp").replace("mode=multi", "mode=packet-up")
    return [grpc, ws, xhttp, grpc.replace("vless://" + UUID, "trojan://synthetic"), vmess(EDGE)]


def test_all_five_ipv6_variants_keep_tls_verification_and_omit_ech() -> None:
    profiles = [normalize(link) for link in variants()]
    assert all(p is not None for p in profiles)
    accepted = [p for p in profiles if p is not None and allowed_cdn(p, HOSTS)]
    assert len(accepted) == 5
    assert apply_cdn_ech(accepted, ECH, HOSTS) == accepted
    assert apply_cdn_ech(accepted, ECH, HOSTS, include_plain_tls=True) == accepted
    uris = base64.b64decode(URIRenderer().render(accepted)).decode().splitlines()
    configs = json.loads(XrayRenderer().render(accepted))
    for uri, config in zip(uris, configs, strict=True):
        assert normalize(uri) is not None
        assert "ech" not in parse_qs(urlsplit(uri).query)
        stream = config["outbounds"][0]["streamSettings"]
        tls = stream["tlsSettings"]
        assert tls["serverName"] == "titan.example" and tls["allowInsecure"] is False
        assert "echConfigList" not in tls and "cipherSuites" not in tls
        assert "finalmask" not in stream and "extra" not in stream.get("xhttpSettings", {})


@pytest.mark.parametrize("address", ["2001:db8::1", "192.0.2.1", "188.114.97.6"])
def test_non_cloudflare_ipv6_and_all_ipv4_literals_stay_rejected(address: str) -> None:
    for link in variants():
        endpoint = f"[{address}]" if ":" in address else address
        if link.startswith("vmess://"):
            assert normalize(vmess(address)) is None
        else:
            assert normalize(link.replace(f"[{EDGE}]", endpoint)) is None


def test_ipv6_requires_explicit_allowlist_and_matching_sni_http_identity() -> None:
    profile = normalize(variants()[0])
    assert profile is not None
    assert not allowed_cdn(profile, ())
    assert not allowed_cdn(replace(profile, sni="other.example"), HOSTS)
    assert not allowed_cdn(replace(profile, authority="other.example"), HOSTS)
    assert not allowed_cdn(replace(profile, authority=""), HOSTS)


def test_ipv6_host_add_remove_follows_marzban_without_changing_customer_url(
    client: TestClient,
) -> None:
    app = cast(FastAPI, client.app)
    registration = create(client)
    path = "/s/" + str(registration["token"])

    class Backend:
        links = variants()

        async def configurations(self, username: str) -> list[str]:
            return self.links

    backend = Backend()
    app.state.backends = {"marzban-default": backend}
    app.state.settings.profile_source = "marzban"
    app.state.settings.allowed_cdn_hosts = HOSTS
    app.state.settings.cdn_ech_config = ECH
    response = client.get(path)
    assert response.status_code == 200
    assert len(base64.b64decode(response.text).decode().splitlines()) == 5
    backend.links = variants()[:1]
    assert len(base64.b64decode(client.get(path).text).decode().splitlines()) == 1
    backend.links = [variants()[0].replace("sni=titan.example", "sni=other.example")]
    assert client.get(path).status_code == 503
