import base64
import json
from dataclasses import replace
from typing import cast
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from keyholder.rendering.profiles import apply_fragmentation, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from tests.conftest import GRPC, TCP, TCP6
from tests.test_api import create


def test_fragment_pilot_preserves_originals_and_skips_ech_and_unselected() -> None:
    tcp, cdn, ipv6 = normalize(TCP), normalize(GRPC), normalize(TCP6)
    assert tcp and cdn and ipv6
    ech = replace(cdn, ech_config_list="cloudflare-ech.com+https://1.1.1.1/dns-query")
    profiles = [tcp, cdn, ipv6, ech]
    delivered = apply_fragmentation(profiles, ("tcp_reality", "grpc_cdn"))
    assert delivered[:4] == profiles and len(delivered) == 6
    for p, packets in zip(delivered[4:], ("1-1", "tlshello"), strict=True):
        assert p.name.endswith(" | FRAG") and p.fingerprint == "chrome"
        uri = base64.b64decode(URIRenderer().render([p])).decode().strip()
        mask = json.loads(parse_qs(urlsplit(uri).query)["fm"][0])
        config = json.loads(XrayRenderer().render([p]))[0]
        stream = config["outbounds"][0]["streamSettings"]
        assert stream["finalmask"] == mask
        assert mask["tcp"][0]["settings"]["packets"] == packets
        assert stream["security"] == p.security
        assert (
            "finalmask"
            not in json.loads(XrayRenderer().render([tcp]))[0]["outbounds"][0]["streamSettings"]
        )


def test_upstream_cannot_inject_finalmask() -> None:
    p = normalize(TCP.replace("#", "&fm=%7Bmalicious%7D#"))
    assert p and not p.fragment
    assert "fm=" not in base64.b64decode(URIRenderer().render([p])).decode()


def test_fragmentation_is_opt_in_and_scoped_to_backend_account(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    result = create(client)
    url = "/s/" + str(result["token"])
    app.state.settings.profile_source = "upstream"

    class Backend:
        async def configurations(self, username: str) -> list[str]:
            return [TCP]

    app.state.backends = {"marzban-default": Backend()}
    app.state.settings.fragmentation_accounts = ("different-backend/alice",)
    baseline = client.get(url).text
    assert "fm=" not in base64.b64decode(baseline).decode()
    app.state.settings.fragmentation_accounts = ("marzban-default/alice",)
    assert len(base64.b64decode(client.get(url).text).splitlines()) == 2
    configs = client.get(url + "?format=xray").json()
    assert len(configs) == 2
    assert "finalmask" in configs[1]["outbounds"][0]["streamSettings"]
    app.state.settings.fragmentation_accounts = ()
    assert client.get(url).text == baseline
