import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from keyholder.rendering.profiles import generate_profiles, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer, select_renderer
from keyholder.schemas import ECHSettings, Policy
from tests.conftest import LINK, UUID


@pytest.mark.parametrize(
    ("transport", "security", "kind", "mode", "flow"),
    [
        ("xhttp", "reality", "xhttp_reality", "stream-one", None),
        ("raw", "reality", "tcp_reality", None, "xtls-rprx-vision"),
        ("xhttp", "tls", "xhttp_cdn", "stream-up", None),
        ("ws", "tls", "ws_cdn", None, None),
    ],
)
def test_profiles(
    transport: str, security: str, kind: str, mode: str | None, flow: str | None
) -> None:
    link = f"vless://{UUID}@example.com:443?type={transport}&security={security}&sni=example.com&pbk=publickey&sid=ab&extra=%7Bbad&flow=xtls-rprx-vision"
    profiles = generate_profiles([link], Policy(), "")
    assert profiles[0].kind == kind
    uri = base64.b64decode(URIRenderer().render(profiles)).decode().strip()
    q = parse_qs(urlsplit(uri).query)
    assert "extra" not in q
    assert q.get("mode", [None])[0] == mode
    assert q.get("flow", [None])[0] == flow
    if transport == "ws":
        assert q["alpn"] == ["http/1.1"]
    if transport == "xhttp" and security == "tls":
        assert q["alpn"] == ["h2,http/1.1"]
    outbound = json.loads(XrayRenderer().render(profiles))[0]["outbounds"][0]
    assert outbound["mux"] == {"enabled": False}
    assert outbound["settings"]["vnext"][0]["users"][0].get("flow") == flow


def test_static_ech_variant_and_uri_fallback() -> None:
    ech = base64.b64encode(b"\x00\x04\xfe\x0d\x00\x00").decode()
    ECHSettings(ech_config_list=ech)
    profiles = generate_profiles([LINK], Policy(ech_enabled=True), ech)
    assert len(profiles) == 2
    configs = json.loads(XrayRenderer().render(profiles))
    assert configs[1]["outbounds"][0]["streamSettings"]["tlsSettings"]["echConfigList"] == ech
    assert "echConfigList" not in configs[0]["outbounds"][0]["streamSettings"]["tlsSettings"]
    assert len(base64.b64decode(URIRenderer().render(profiles)).decode().splitlines()) == 1
    with pytest.raises(ValueError):
        generate_profiles([LINK], Policy(ech_enabled=True), "")
    with pytest.raises(ValidationError):
        ECHSettings(ech_config_list="invalid")
    with pytest.raises(ValueError):
        URIRenderer().render([profiles[1]])
    assert isinstance(select_renderer(None, "v2rayN/7.25.4"), URIRenderer)
    assert isinstance(select_renderer("xray", ""), XrayRenderer)


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.test",
        "vless://bad@x:443",
        LINK.replace(":443", ":99999"),
        LINK + "&type=ws",
        LINK.replace("type=xhttp", "type=grpc"),
        LINK + "\n",
    ],
)
def test_malformed_links_rejected(link: str) -> None:
    # Appending to fragment doesn't introduce query duplication.
    if link == LINK + "&type=ws":
        link = LINK.replace("type=xhttp", "type=xhttp&type=ws")
    assert normalize(link) is None
