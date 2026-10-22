import base64
import json

import pytest

from keyholder.policies import SUPPORTED_KINDS
from keyholder.rendering.profiles import generate_profiles, normalize
from keyholder.rendering.renderers import URIRenderer, XrayRenderer
from keyholder.schemas import Policy
from tests.support import GRPC, TCP6, UUID, vmess


@pytest.mark.parametrize(
    "link,kind,protocol",
    [
        (
            GRPC.replace("vless://" + UUID, "trojan://synthetic-password"),
            "trojan_grpc_cdn",
            "trojan",
        ),
        (
            TCP6.replace("vless://" + UUID, "trojan://synthetic-password"),
            "trojan_reality_ipv6",
            "trojan",
        ),
        (vmess(), "vmess_httpupgrade_cdn", "vmess"),
    ],
)
def test_new_protocol_roundtrip_and_security(link: str, kind: str, protocol: str) -> None:
    profile = normalize(link)
    assert profile is not None and profile.kind == kind and profile.protocol == protocol
    policy = Policy.model_validate({"profiles": list(SUPPORTED_KINDS)})
    profiles = generate_profiles([link], policy)
    uri = base64.b64decode(URIRenderer().render(profiles)).decode().strip()
    again = normalize(uri)
    assert again is not None and again.kind == kind and again.password == profile.password
    outbound = json.loads(XrayRenderer().render(profiles))[0]["outbounds"][0]
    assert outbound["protocol"] == protocol and outbound["mux"]["enabled"] is False
    if profile.security == "tls":
        assert outbound["streamSettings"]["tlsSettings"]["allowInsecure"] is False
    if protocol == "trojan":
        assert outbound["settings"]["servers"][0]["password"] == profile.password
        assert "flow" not in uri
    else:
        assert outbound["settings"]["vnext"][0]["users"][0]["alterId"] == 0


@pytest.mark.parametrize(
    "link",
    [
        vmess("192.0.2.1"),
        vmess("2001:db8::1"),
        TCP6.replace("vless://" + UUID, "trojan://secret").replace("[2001:db8::1]", "192.0.2.1"),
        GRPC.replace("vless://" + UUID, "trojan://secret").replace("titan.example", "192.0.2.1"),
        "vmess://" + base64.b64encode(b'{"port":null}').decode(),
    ],
)
def test_new_protocols_reject_unsafe_origin_or_malformed_data(link: str) -> None:
    assert normalize(link) is None
