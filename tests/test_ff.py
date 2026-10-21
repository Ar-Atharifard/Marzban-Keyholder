import base64
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr, ValidationError

from keyholder.config import Settings
from keyholder.rendering.profiles import FF_CIPHERS, delivery_profiles, ff_mask, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from tests.conftest import GRPC, TCP


def settings() -> Settings:
    return Settings(
        admin_key=SecretStr("a" * 40),
        allowed_cdn_hosts=("titan.example", "tls.example"),
        allowed_cdn_networks=("188.114.96.0/20",),
        ff_accounts=("panel/OWNER",),
        ff_address="188.114.98.0",
        fragmentation_accounts=("panel/OWNER",),
        fragmentation_kinds=("tcp_reality",),
        fragmentation_hosts=("example.com",),
    )


def test_ff_is_explicit_account_only_and_keeps_base_profiles() -> None:
    profile = normalize(GRPC)
    assert profile is not None
    s = settings()
    assert delivery_profiles([profile], s, "panel/alice") == [profile]
    result = delivery_profiles([profile], s, "panel/OWNER")
    assert result[0] == profile and len(result) == 2
    ff = result[1]
    assert ff.address == "188.114.98.0" and ff.sni == profile.sni
    assert ff.host == profile.host and ff.authority == profile.authority
    assert ff.fingerprint == "unsafe" and ff.alpn == ("h2",)
    assert ff.ff and not ff.ech_config_list and not ff.fragment
    xhttp = replace(profile, kind="xhttp_tls_cdn", transport="xhttp")
    assert delivery_profiles([xhttp], s, "panel/OWNER")[-1].alpn == ("h2", "http/1.1")


def test_ff_serializes_the_exact_patt_preset_and_keeps_certificate_verification() -> None:
    profile = normalize(GRPC)
    assert profile is not None
    ff = delivery_profiles([profile], settings(), "panel/OWNER")[-1]
    uri = base64.b64decode(URIRenderer().render([ff])).decode()
    query = parse_qs(urlsplit(uri).query)
    assert query["cs"] == [FF_CIPHERS] and query["fp"] == ["unsafe"]
    assert json.loads(query["fm"][0]) == ff_mask() and "ech" not in query
    assert ff_mask()["tcp"] == [
        {
            "type": "fragment",
            "settings": {
                "packets": "tlshello",
                "lengths": ["0", "104", "1"],
                "delays": ["0"],
                "maxSplit": "0",
            },
        },
        {
            "type": "fragment",
            "settings": {
                "packets": "1-1",
                "lengths": ["114", "1"],
                "delays": ["1"],
                "maxSplit": "11",
            },
        },
    ]
    config = json.loads(XrayRenderer().render([ff]))[0]["outbounds"][0]["streamSettings"]
    assert config["finalmask"] == ff_mask()
    assert config["tlsSettings"]["cipherSuites"] == FF_CIPHERS
    assert config["tlsSettings"]["minVersion"] == "1.2"
    assert config["tlsSettings"]["allowInsecure"] is False
    # Unknown upstream cs/fm are never trusted as deployment policy.
    imported = normalize(uri.strip(), settings().allowed_cdn_networks)
    assert imported is not None and not imported.ff


def test_fragment_host_scope_keeps_only_the_working_realities() -> None:
    profile = normalize(TCP)
    assert profile is not None
    s = settings()
    s.fragmentation_hosts = (profile.address,)
    domestic = replace(profile, address="gate.example", name="IR")
    result = delivery_profiles([profile, domestic], s, "panel/OWNER")
    assert len(result) == 3 and result[-1].address == profile.address and result[-1].fragment
    assert all(not p.ff for p in result)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "203.0.113.1", "8.8.8.8", "not-an-ip"]
)
def test_ff_rejects_untrusted_or_private_endpoints(address: str) -> None:
    with pytest.raises(ValidationError, match="public edge IP"):
        Settings(
            admin_key=SecretStr("a" * 40),
            ff_accounts=("panel/OWNER",),
            ff_address=address,
            allowed_cdn_networks=("188.114.96.0/20",),
        )
