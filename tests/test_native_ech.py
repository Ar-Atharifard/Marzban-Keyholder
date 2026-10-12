"""Native ECH is trusted delivery configuration, independent of customer identity."""

import base64
import json
from dataclasses import replace
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from keyholder.config import Settings
from keyholder.rendering.profiles import apply_cdn_ech, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from tests.conftest import ADMIN_KEY, GRPC, LINK, TCP, TCP6, UUID
from tests.test_api import create
from tests.test_protocol_expansion import vmess

ECH = "cloudflare-ech.com+https://8.8.8.8/dns-query"
HOSTS = ("titan.example",)


def test_ech_covers_five_cdn_transports_without_weakening_direct_profiles() -> None:
    grpc = GRPC.replace("sni=tls.example", "sni=titan.example")
    ws = grpc.replace("type=grpc", "type=ws")
    xhttp = (
        grpc.replace("type=grpc", "type=xhttp")
        .replace("mode=multi", "mode=packet-up")
        .replace("#Titan", "&extra=ignored#Titan")
    )
    links = [
        grpc,
        ws,
        xhttp,
        grpc.replace("vless://" + UUID, "trojan://test-secret"),
        vmess(),
        TCP,
        TCP6,
        LINK,
    ]
    originals = [normalize(link) for link in links]
    assert all(p is not None for p in originals)
    profiles = [p for p in originals if p is not None]
    enabled = apply_cdn_ech(profiles, ECH, HOSTS)
    uris = base64.b64decode(URIRenderer().render(enabled)).decode().splitlines()
    configs = json.loads(XrayRenderer().render(enabled))
    for index, (profile, uri, config) in enumerate(zip(enabled, uris, configs, strict=True)):
        stream = config["outbounds"][0]["streamSettings"]
        if index < 5:
            query = parse_qs(urlsplit(uri).query)
            assert query["ech"] == [ECH] and query["fp"] == ["chrome"]
            assert stream["tlsSettings"]["echConfigList"] == ECH
            assert stream["tlsSettings"]["allowInsecure"] is False
            assert normalize(uri) is not None
        else:
            assert profile == profiles[index] and "ech" not in parse_qs(urlsplit(uri).query)
            assert "echConfigList" not in stream["realitySettings"]
        assert "extra" not in stream.get("xhttpSettings", {})
        assert "extra" not in parse_qs(urlsplit(uri).query)
        assert "cipherSuites" not in stream.get("tlsSettings", {})
        assert "finalmask" not in stream
    # Explicitly protect the legacy byte-for-byte path when the feature is disabled.
    assert URIRenderer().render(apply_cdn_ech(profiles, "", HOSTS)) == URIRenderer().render(
        profiles
    )
    assert apply_cdn_ech(profiles, ECH, ()) == profiles
    foreign_sni = replace(profiles[0], sni="other.example")
    assert apply_cdn_ech([foreign_sni], ECH, HOSTS) == [foreign_sni]


def test_ech_update_preserves_url_and_follows_marzban_selections(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    registered = create(client)
    url = "/s/" + str(registered["token"])
    grpc = GRPC.replace("sni=tls.example", "sni=titan.example")

    class Backend:
        links = [grpc, TCP]

        async def configurations(self, username: str) -> list[str]:
            return self.links

    upstream = Backend()
    app.state.backends = {"marzban-default": upstream}
    app.state.settings.profile_source = "marzban"
    app.state.settings.allowed_cdn_hosts = HOSTS
    before = client.get(url)
    assert before.status_code == 200
    assert all(
        "ech" not in parse_qs(urlsplit(u).query)
        for u in base64.b64decode(before.text).decode().splitlines()
    )
    app.state.settings.cdn_ech_config = ECH
    after = client.get(url)
    assert after.status_code == 200
    assert after.headers["cache-control"] == "no-store"
    assert parse_qs(urlsplit(base64.b64decode(after.text).decode().splitlines()[0]).query)[
        "ech"
    ] == [ECH]
    upstream.links = [TCP]
    assert client.get(url).text == URIRenderer().render([p for p in [normalize(TCP)] if p])


@pytest.mark.parametrize(
    "value",
    [
        "udp://1.1.1.1",
        "fixed-key",
        "https://u:p@dns.example/dns-query",
        "https://dns.example/wrong",
        "https://dns.example/dns-query?x=1",
        "https://dns.example:wrong/dns-query",
        "a b+https://dns.example/dns-query",
    ],
)
def test_ech_rejects_static_or_invalid_resolvers(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(admin_key=SecretStr(ADMIN_KEY), cdn_ech_config=value)


def test_ech_accepts_dynamic_https_configuration() -> None:
    assert Settings(admin_key=SecretStr(ADMIN_KEY), cdn_ech_config=ECH).cdn_ech_config == ECH


def test_compatibility_keeps_existing_entries_and_verifies_plain_tls() -> None:
    grpc = normalize(GRPC.replace("sni=tls.example", "sni=titan.example"))
    direct = normalize(TCP)
    assert grpc is not None and direct is not None
    originals = [grpc, direct]
    existing = apply_cdn_ech(originals, ECH, HOSTS)
    paired = apply_cdn_ech(originals, ECH, HOSTS, include_plain_tls=True)
    assert paired[:2] == originals
    assert len(paired) == 3
    plain = paired[0]
    assert plain == replace(grpc, fingerprint="chrome")
    assert paired[-1] == replace(existing[0], name=grpc.name + " [ECH fallback]")
    assert plain.uuid == grpc.uuid and plain.kind == grpc.kind
    assert not plain.ech_config_list
    stream = json.loads(XrayRenderer().render([plain]))[0]["outbounds"][0]["streamSettings"]
    assert stream["tlsSettings"]["allowInsecure"] is False
    assert "echConfigList" not in stream["tlsSettings"]
    assert apply_cdn_ech(originals, "", HOSTS, True) == originals
    assert apply_cdn_ech(originals, ECH, (), True) == originals


def test_compatibility_follows_upstream_selection_and_preserves_url(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    registered = create(client)
    url = "/s/" + str(registered["token"])

    class Backend:
        links = [GRPC.replace("sni=tls.example", "sni=titan.example"), TCP]

        async def configurations(self, username: str) -> list[str]:
            return self.links

    upstream = Backend()
    app.state.backends = {"marzban-default": upstream}
    app.state.settings.profile_source = "upstream"
    app.state.settings.allowed_cdn_hosts = HOSTS
    app.state.settings.cdn_ech_config = ECH
    before = client.get(url)
    app.state.settings.cdn_tls_compatibility = True
    after = client.get(url)
    assert before.status_code == after.status_code == 200
    old_uris = base64.b64decode(before.text).decode().splitlines()
    uris = base64.b64decode(after.text).decode().splitlines()
    assert "ech" not in parse_qs(urlsplit(uris[0]).query)
    assert uris[1] == old_uris[1]
    assert len(uris) == 3 and parse_qs(urlsplit(uris[-1]).query)["ech"] == [ECH]
    upstream.links = [TCP]
    assert client.get(url).text == URIRenderer().render([p for p in [normalize(TCP)] if p])
