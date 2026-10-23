"""Add a managed domestic entry without changing existing foreign routing."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


def add_transport(
    core: dict[str, Any], inbound: dict[str, Any], existing_tag: str
) -> dict[str, Any]:
    """Share the domestic routing policy with another REALITY transport."""
    result = deepcopy(core)
    tags = {item["tag"] for item in core["inbounds"]}
    if existing_tag not in tags or inbound["tag"] in tags:
        raise ValueError("Existing domestic entry required; new tag must be unique")
    stream = inbound.get("streamSettings", {})
    reality = stream.get("realitySettings", {})
    if reality.get("target") and reality.get("dest") and reality["target"] != reality["dest"]:
        raise ValueError("REALITY target and legacy dest must not conflict")
    if (
        inbound.get("listen") != "127.0.0.1"
        or stream.get("security") != "reality"
        or stream.get("network") not in {"tcp", "xhttp", "grpc"}
        or not stream.get("realitySettings", {}).get("publicKey")
        or not stream.get("sockopt", {}).get("acceptProxyProtocol")
    ):
        raise ValueError("Expected loopback REALITY behind the gateway")
    rules = [
        rule for rule in result["routing"]["rules"] if existing_tag in rule.get("inboundTag", [])
    ]
    local_rules = [rule for rule in rules if "ip" in rule or "domain" in rule]
    pinned = [rule for rule in rules if "ip" not in rule and "domain" not in rule]
    if (
        len(local_rules) != 3
        or len(pinned) > 1
        or (pinned and core["routing"].get("domainStrategy") != "IPOnDemand")
    ):
        raise ValueError("Review domestic split-routing rules before extending them")
    for rule in rules:
        rule["inboundTag"].append(inbound["tag"])
    result["inbounds"].append(deepcopy(inbound))
    return result


def add_entry(
    core: dict[str, Any], inbound: dict[str, Any], exit_proxy: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(core)
    tag = inbound["tag"]
    if tag in {item["tag"] for item in core["inbounds"]}:
        raise ValueError("Domestic inbound already exists")
    if inbound.get("listen") != "127.0.0.1":
        raise ValueError("The managed listener must stay behind the local gateway")
    if inbound.get("streamSettings", {}).get("security") != "reality":
        raise ValueError("Domestic entry requires REALITY")
    if inbound["streamSettings"].get("network") != "tcp":
        raise ValueError("Use tcp: older Marzban live updates strip Vision from the raw alias")
    reality = inbound["streamSettings"].get("realitySettings", {})
    if not reality.get("publicKey"):
        raise ValueError("Set the matching REALITY publicKey explicitly for subscription export")
    if (
        exit_proxy["protocol"] != "socks"
        or exit_proxy["settings"]["servers"][0]["address"] != "127.0.0.1"
    ):
        raise ValueError("Foreign exit must use the authenticated loopback tunnel")
    if not exit_proxy["settings"]["servers"][0].get("users"):
        raise ValueError("Foreign exit authentication required")
    if core.get("dns"):
        raise ValueError("Review existing DNS before adding the shared trusted resolver")
    options = component_settings(
        "domestic_routing",
        {
            "trusted_dns_servers": ["https://1.1.1.1/dns-query"],
            "local_geoip": ["geoip:ir"],
            "xudp_concurrency": 8,
        },
    )
    result["dns"] = {"servers": options["trusted_dns_servers"], "tag": "TRUSTED_DNS"}
    routing = result.setdefault("routing", {})
    if routing.get("domainStrategy", "AsIs") != "IPIfNonMatch":
        raise ValueError("Review routing: IPIfNonMatch is required")
    old_tags = [item["tag"] for item in core["inbounds"]]
    old_default = core["outbounds"][0]["tag"]
    for rule in routing.get("rules", []):
        if not rule.get("inboundTag"):
            rule["inboundTag"] = old_tags
    # No domestic catch-all: IPIfNonMatch must resolve names and retry IP rules.
    routing["rules"] = [
        {"type": "field", "inboundTag": ["TRUSTED_DNS"], "outboundTag": exit_proxy["tag"]},
        {"type": "field", "inboundTag": [tag], "ip": ["geoip:private"], "outboundTag": "BLOCK"},
        {
            "type": "field",
            "inboundTag": [tag],
            "domain": ["geosite:private"],
            "outboundTag": "BLOCK",
        },
        {
            "type": "field",
            "inboundTag": [tag],
            "ip": options["local_geoip"],
            "outboundTag": old_default,
        },
        *routing.get("rules", []),
        {"type": "field", "inboundTag": old_tags, "outboundTag": old_default},
    ]
    tunnel = deepcopy(exit_proxy)
    tunnel["mux"] = {
        "enabled": True,
        "concurrency": -1,
        "xudpConcurrency": options["xudp_concurrency"],
        "xudpProxyUDP443": "allow",
    }
    result["outbounds"].insert(0, tunnel)
    result["inbounds"].append(deepcopy(inbound))
    return result


def add_backhaul_entry(
    core: dict[str, Any], inbound: dict[str, Any], existing_tag: str, exit_proxy: dict[str, Any]
) -> dict[str, Any]:
    """Keep domestic classification before selecting a different foreign backhaul."""
    tag = exit_proxy.get("tag")
    servers = exit_proxy.get("settings", {}).get("servers", [])
    if (
        not tag
        or tag in {item["tag"] for item in core["outbounds"]}
        or exit_proxy.get("protocol") != "socks"
        or len(servers) != 1
        or servers[0].get("address") != "127.0.0.1"
        or not servers[0].get("users")
        or core.get("routing", {}).get("domainStrategy") not in {"IPIfNonMatch", "IPOnDemand"}
    ):
        raise ValueError("Unique authenticated loopback exit and IP classification required")
    result = add_transport(core, inbound, existing_tag)
    result["outbounds"].append(deepcopy(exit_proxy))
    # Resolve at the earlier IP rules before the per-entry fallback can match.
    result["routing"]["domainStrategy"] = "IPOnDemand"
    result["routing"]["rules"].append(
        {
            "type": "field",
            "inboundTag": [inbound["tag"]],
            "outboundTag": tag,
        }
    )
    return result
