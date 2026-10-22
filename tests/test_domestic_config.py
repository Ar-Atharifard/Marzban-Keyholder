from copy import deepcopy
from typing import Any

import pytest

from scripts.domestic_config import add_entry, add_transport
from tests.support import domestic_inputs as inputs


def test_domestic_routing_keeps_foreign_policy_and_resolves_before_default() -> None:
    core, inbound, exit_proxy = inputs()
    before = deepcopy(core)
    result = add_entry(core, inbound, exit_proxy)
    assert core == before
    assert result["outbounds"][0]["tag"] == "TUNNEL"
    assert result["outbounds"][0]["mux"] == {
        "enabled": True,
        "concurrency": -1,
        "xudpConcurrency": 8,
        "xudpProxyUDP443": "allow",
    }
    rules = result["routing"]["rules"]
    assert result["dns"] == {"servers": ["https://1.1.1.1/dns-query"], "tag": "TRUSTED_DNS"}
    assert rules[0] == {"type": "field", "inboundTag": ["TRUSTED_DNS"], "outboundTag": "TUNNEL"}
    assert rules[1]["ip"] == ["geoip:private"]
    assert rules[3]["ip"] == ["geoip:ir"]
    assert rules[3]["outboundTag"] == "DIRECT"
    assert rules[4]["outboundTag"] == "BLOCK"
    assert rules[4]["inboundTag"] == ["foreign"]
    assert rules[-1] == {"type": "field", "inboundTag": ["foreign"], "outboundTag": "DIRECT"}
    assert not any(
        r.get("inboundTag") == ["domestic"] and not ("ip" in r or "domain" in r) for r in rules
    )


@pytest.mark.parametrize(
    "problem",
    ["public", "plaintext", "no-auth", "strategy", "duplicate", "raw-alias", "no-key", "dns"],
)
def test_reject_unsafe_or_repeated_configuration(problem: Any) -> None:
    core, inbound, exit_proxy = inputs()
    if problem == "public":
        inbound["listen"] = "0.0.0.0"
    elif problem == "plaintext":
        inbound["streamSettings"]["security"] = "none"
    elif problem == "no-auth":
        exit_proxy["settings"]["servers"][0].pop("users")
    elif problem == "strategy":
        core["routing"]["domainStrategy"] = "AsIs"
    elif problem == "raw-alias":
        inbound["streamSettings"]["network"] = "raw"
    elif problem == "no-key":
        inbound["streamSettings"]["realitySettings"].pop("publicKey")
    elif problem == "dns":
        core["dns"] = {"servers": ["localhost"]}
    else:
        core["inbounds"].append(inbound)
    with pytest.raises(ValueError):
        add_entry(core, inbound, exit_proxy)


def test_second_transport_shares_only_domestic_policy() -> None:
    core, inbound, exit_proxy = inputs()
    original = add_entry(core, inbound, exit_proxy)
    second = deepcopy(inbound)
    second["tag"] = "domestic-xhttp"
    second["streamSettings"].update(network="xhttp", sockopt={"acceptProxyProtocol": True})
    invalid = deepcopy(second)
    invalid["streamSettings"]["realitySettings"].update(
        target="original.example:443", dest="different.example:443"
    )
    with pytest.raises(ValueError, match="conflict"):
        add_transport(original, invalid, "domestic")
    result = add_transport(original, second, "domestic")
    assert len(original["inbounds"]) == 2
    assert len(result["inbounds"]) == 3
    assert result["routing"]["rules"][4:] == original["routing"]["rules"][4:]
    for rule in result["routing"]["rules"][1:4]:
        assert rule["inboundTag"] == ["domestic", "domestic-xhttp"]
    with pytest.raises(ValueError):
        add_transport(result, second, "domestic")


def test_added_transport_keeps_the_selected_backhaul_and_all_local_guards() -> None:
    from scripts.domestic_config import add_backhaul_entry

    core, inbound, proxy = inputs()
    core = add_entry(core, inbound, proxy)
    first = deepcopy(inbound)
    first["tag"] = "pinned"
    first["streamSettings"]["sockopt"] = {"acceptProxyProtocol": True}
    proxy["tag"] = "SECOND"
    core = add_backhaul_entry(core, first, "domestic", proxy)
    second = deepcopy(first)
    second["tag"] = "pinned-grpc"
    second["streamSettings"]["network"] = "grpc"
    result = add_transport(core, second, "pinned")
    rules = [r for r in result["routing"]["rules"] if "pinned-grpc" in r.get("inboundTag", [])]
    assert len(rules) == 4
    assert [r["outboundTag"] for r in rules] == ["BLOCK", "BLOCK", "DIRECT", "SECOND"]
    assert result["outbounds"] == core["outbounds"]
    assert all("pinned-grpc" not in r.get("inboundTag", []) for r in core["routing"]["rules"])
