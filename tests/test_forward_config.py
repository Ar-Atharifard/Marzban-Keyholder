from copy import deepcopy
from unittest.mock import patch

import pytest

from scripts.backhaul_probe import healthy
from scripts.domestic_config import add_backhaul_entry, add_entry
from scripts.forward_config import configurations
from tests.test_domestic_config import inputs


def test_forward_peers_use_vision_and_separate_public_private_keys():
    server, client = configurations(
        "2001:db8::1",
        "example.org",
        "identity",
        "private",
        "public",
        "abcd",
        {"user": "infra", "pass": "secret"},
        "2001:db8::2",
    )
    assert server["inbounds"][0]["streamSettings"]["realitySettings"]["privateKey"] == "private"
    outbound = client["outbounds"][0]
    assert outbound["streamSettings"]["realitySettings"]["publicKey"] == "public"
    assert "private" not in str(client)
    assert outbound["sendThrough"] == "2001:db8::2"
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert client["inbounds"][0]["listen"] == "127.0.0.1"
    assert client["inbounds"][0]["settings"]["auth"] == "password"
    assert server["outbounds"][0]["settings"]["servers"][0]["address"] == "127.0.0.1"


def test_forward_profile_keeps_domestic_and_private_rules_before_foreign_ip_catchall():
    core, inbound, proxy = inputs()
    core = add_entry(core, inbound, proxy)
    second = deepcopy(inbound)
    second.update(tag="forward")
    second["streamSettings"]["sockopt"] = {"acceptProxyProtocol": True}
    proxy["tag"] = "FORWARD"
    before = deepcopy(core)
    result = add_backhaul_entry(core, second, "domestic", proxy)
    assert core == before
    rules = result["routing"]["rules"]
    assert all("forward" in rule["inboundTag"] for rule in rules[1:4])
    assert rules[1]["outboundTag"] == "BLOCK"
    assert rules[3]["outboundTag"] == "DIRECT"
    assert rules[-1] == {
        "type": "field",
        "inboundTag": ["forward"],
        "outboundTag": "FORWARD",
    }
    assert result["routing"]["domainStrategy"] == "IPOnDemand"
    assert rules[-1]["outboundTag"] == "FORWARD"


def test_probe_uses_certificate_verification_and_keeps_secrets_off_argv():
    with patch("scripts.backhaul_probe.subprocess.run") as run:
        run.return_value.returncode = 0
        assert healthy(19987, {"user": "infra", "pass": "private-password"})
        args = run.call_args.args[0]
        assert "private-password" not in str(args)
        assert "--insecure" not in args
        assert run.call_args.kwargs["input"] == 'proxy-user = "infra:private-password"\n'


def test_probe_falls_back_and_rejects_unknown_port():
    with patch("scripts.backhaul_probe.subprocess.run") as run:
        run.return_value.returncode = 28
        assert not healthy(19987, {"user": "a", "pass": "b"})
        assert run.call_count == 2
    with pytest.raises(ValueError):
        healthy(22, {"user": "a", "pass": "b"})
