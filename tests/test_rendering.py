import base64
import json
from urllib.parse import parse_qs, quote, unquote, urlsplit

import pytest

from keyholder.rendering.profiles import decode_base64, generate_profiles, normalize
from keyholder.rendering.renderers import Renderer, URIRenderer, XrayRenderer
from keyholder.schemas import Policy
from tests.conftest import ALL, GRPC, IPV6, KINDS, LINK, PASSWORD, PBK, SS, TCP, UUID


def rendered(links: list[str], policy: Policy) -> tuple[list[str], list[dict[str, object]]]:
    profiles = generate_profiles(links, policy)
    uris = base64.b64decode(URIRenderer().render(profiles), validate=True).decode().splitlines()
    configs = json.loads(XrayRenderer().render(profiles))
    return uris, configs


@pytest.mark.parametrize("index", range(5))
def test_five_families_and_json_consistency(index: int) -> None:
    policy = Policy.model_validate({"profiles": KINDS})
    p = normalize(ALL[index])
    assert p is not None and p.kind == KINDS[index]
    uris, configs = rendered([ALL[index]], policy)
    u = urlsplit(uris[0])
    outbound = configs[0]["outbounds"][0]  # type: ignore[index]
    assert u.hostname == p.address and u.port == p.port
    assert outbound["mux"] == {"enabled": False}
    if p.kind == "shadowsocks_ipv6":
        assert u.scheme == "ss"
        assert decode_base64(u.username or "").decode() == f"aes-128-gcm:{PASSWORD}"
        assert outbound["protocol"] == "shadowsocks"
        assert outbound["settings"]["servers"][0] == {
            "address": IPV6,
            "port": 10444,
            "method": "aes-128-gcm",
            "password": PASSWORD,
        }
        assert f"@[{IPV6}]:10444" in uris[0]
        return
    q = parse_qs(u.query, keep_blank_values=True)
    assert u.username == UUID
    assert outbound["settings"]["vnext"][0]["users"][0]["id"] == UUID
    assert q["fp"] == [p.fingerprint] and q["sni"] == [p.sni]
    assert all(k not in q for k in ["extra", "ech", "mux", "smux"])
    if p.security == "reality":
        assert q["pbk"] == [PBK] and q["sid"] == [p.short_id]
        tls = outbound["streamSettings"]["realitySettings"]
        assert tls["publicKey"] == PBK and tls["shortId"] == p.short_id
        if index in {0, 3}:
            assert q["flow"] == ["xtls-rprx-vision"]
            assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    if index == 3:
        assert f"@[{IPV6}]:10443" in uris[0]
        assert q["type"] == ["raw"]


def test_xhttp_extra_preserves_valid_fields() -> None:
    link = LINK.replace("path=%2Fx", "path=%2Fpath%3Fx%3D1&mode=stream-up&fp=firefox&alpn=h2")
    uris, configs = rendered([link], Policy())
    q = parse_qs(urlsplit(uris[0]).query)
    assert q["path"] == ["/path?x=1"]
    assert q["host"] == ["direct.example"]
    assert q["mode"] == ["stream-up"] and q["fp"] == ["firefox"]
    assert q["alpn"] == ["h2"]
    assert "flow" not in q and "extra" not in q
    outbound = configs[0]["outbounds"][0]  # type: ignore[index]
    assert outbound["streamSettings"]["xhttpSettings"] == {
        "host": "direct.example",
        "path": "/path?x=1",
        "mode": "stream-up",
    }
    assert "extra" not in json.dumps(configs)
    assert "flow" not in outbound["settings"]["vnext"][0]["users"][0]


def test_extra_removal_does_not_strip_path_query_or_remark() -> None:
    link = LINK.replace("path=%2Fx", "path=%2Fpath%3Fextra%3Dkeep").replace(
        "#Direct", "#extra%20remark"
    )
    uris, configs = rendered([link], Policy())
    u = urlsplit(uris[0])
    query = parse_qs(u.query)
    assert "extra" not in query
    assert query["path"] == ["/path?extra=keep"]
    assert unquote(u.fragment) == "extra remark"
    outbound = configs[0]["outbounds"][0]  # type: ignore[index]
    assert "extra" not in outbound["streamSettings"]["xhttpSettings"]
    assert outbound["streamSettings"]["xhttpSettings"]["path"] == "/path?extra=keep"
    assert configs[0]["remarks"] == "extra remark"


def test_grpc_metadata_and_no_reality_ech_or_vision() -> None:
    uris, configs = rendered([GRPC], Policy(profiles=["grpc_cdn"]))
    q = parse_qs(urlsplit(uris[0]).query)
    assert q["serviceName"] == ["service/name?x=1"]
    assert q["authority"] == ["grpc.example"] and q["mode"] == ["multi"]
    assert q["alpn"] == ["h2,http/1.1"]
    assert all(k not in q for k in ["pbk", "sid", "ech", "flow"])
    assert "%2F" in uris[0] and "%3F" in uris[0]
    outbound = configs[0]["outbounds"][0]  # type: ignore[index]
    stream = outbound["streamSettings"]
    assert stream["grpcSettings"] == {
        "serviceName": "service/name?x=1",
        "multiMode": True,
        "authority": "grpc.example",
    }
    assert stream["tlsSettings"]["alpn"] == ["h2", "http/1.1"]
    assert stream["tlsSettings"]["serverName"] == "tls.example"
    assert "realitySettings" not in stream
    assert "flow" not in outbound["settings"]["vnext"][0]["users"][0]


@pytest.mark.parametrize("encoding", ["urlsafe", "standard", "plaintext", "legacy"])
def test_shadowsocks_encodings(encoding: str) -> None:
    payload = f"aes-128-gcm:{PASSWORD}"
    if encoding == "legacy":
        link = (
            "ss://"
            + base64.b64encode(f"{payload}@[{IPV6}]:10444".encode()).decode().rstrip("=")
            + "#SS"
        )
    else:
        info = (
            quote("aes-128-gcm", safe="") + ":" + quote(PASSWORD, safe="")
            if encoding == "plaintext"
            else (base64.urlsafe_b64encode if encoding == "urlsafe" else base64.b64encode)(
                payload.encode()
            ).decode()
        )
        link = f"ss://{info}@[{IPV6}]:10444#Name%20%2B"
    p = normalize(link)
    assert p is not None and p.password == PASSWORD and p.method == "aes-128-gcm"
    uris, _ = rendered([link], Policy(profiles=["shadowsocks_ipv6"]))
    assert decode_base64(urlsplit(uris[0]).username or "").decode() == payload
    assert unquote(urlsplit(uris[0]).fragment) == p.name


def test_defaults_enable_all_five_and_explicit_policy_still_filters() -> None:
    assert [p.kind for p in generate_profiles(ALL, Policy())] == KINDS
    assert [p.kind for p in generate_profiles(ALL, Policy(profiles=["tcp_reality_ipv6"]))] == [
        "tcp_reality_ipv6"
    ]
    assert generate_profiles(ALL, Policy(profiles=[])) == []
    renderers: list[Renderer] = [URIRenderer(), XrayRenderer()]
    for renderer in renderers:
        with pytest.raises(ValueError):
            renderer.render([])


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example",
        "vless://bad@x:443",
        TCP.replace(":8443", ":99999"),
        TCP.replace(PBK, "broken"),
        TCP.replace("sid=aB12", "sid=gg"),
        TCP.replace("sid=aB12", "sid=ab&sid=cd"),
        TCP + "\n",
        TCP.replace("type=tcp", "type=ws"),
        LINK.replace("security=reality", "security=tls"),
        GRPC.replace("mode=multi", "mode=invalid"),
        GRPC.replace("serviceName=", "serviceName=%0A"),
        SS.replace("ss://", "ss://!"),
        SS + "?plugin=bad",
        "ss://"
        + base64.b64encode(f"2022-blake3-aes-128-gcm:password@[{IPV6}]:10444".encode()).decode(),
        "ss://" + base64.b64encode(f"aes-128-gcm:@[{IPV6}]:10444".encode()).decode(),
    ],
)
def test_malformed_or_obsolete_profiles_rejected(link: str) -> None:
    if link == SS + "?plugin=bad":
        link = SS.replace("#", "?plugin=bad#")
    assert normalize(link) is None


@pytest.mark.parametrize("transport,kind", [("ws", "ws_tls_cdn"), ("xhttp", "xhttp_tls_cdn")])
def test_new_cdn_transports_roundtrip_without_changing_old_defaults(
    transport: str, kind: str
) -> None:
    link = (
        f"vless://{UUID}@titan.example:443?security=tls&type={transport}"
        "&sni=titan.example&host=titan.example&path=%2Flearn%2Ftransport"
        "&mode=packet-up&extra=%7B%22unsafe%22%3Atrue%7D#CDN"
    )
    p = normalize(link)
    assert p is not None and p.kind == kind
    assert generate_profiles([link], Policy()) == []  # Existing policies never expand implicitly.
    policy = Policy.model_validate({"profiles": [kind]})
    uris, configs = rendered([link], policy)
    assert normalize(uris[0]) == p
    stream = configs[0]["outbounds"][0]["streamSettings"]  # type: ignore[index]
    assert stream["tlsSettings"]["allowInsecure"] is False
    assert stream["network"] == transport
    if transport == "ws":
        assert stream["wsSettings"] == {
            "path": "/learn/transport",
            "headers": {"Host": "titan.example"},
        }
    else:
        assert stream["xhttpSettings"] == {
            "path": "/learn/transport",
            "host": "titan.example",
            "mode": "packet-up",
        }
        assert "extra" not in parse_qs(urlsplit(uris[0]).query)
        assert "extra" not in stream["xhttpSettings"]


@pytest.mark.parametrize("transport", ["ws", "xhttp"])
@pytest.mark.parametrize("address", ["192.0.2.5", "[2001:db8::5]"])
def test_cdn_profiles_refuse_literal_origin_addresses(transport: str, address: str) -> None:
    assert normalize(f"vless://{UUID}@{address}:443?security=tls&type={transport}") is None


@pytest.mark.parametrize("method", ["aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305"])
def test_standard_shadowsocks_aead_methods_follow_panel(method: str) -> None:
    import base64
    import json

    from keyholder.rendering.profiles import normalize
    from keyholder.rendering.renderers import URIRenderer, XrayRenderer

    userinfo = base64.urlsafe_b64encode((method + ":synthetic-password").encode()).decode()
    p = normalize("ss://" + userinfo + "@[2001:db8::1]:10444#AEAD")
    assert p is not None and p.method == method
    outbound = json.loads(XrayRenderer().render([p]))[0]["outbounds"][0]
    assert outbound["settings"]["servers"][0]["method"] == method
    uri = base64.b64decode(URIRenderer().render([p])).decode().strip()
    restored = normalize(uri)
    assert restored is not None and restored.method == method
