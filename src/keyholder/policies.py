"""Conservative read compatibility for stored policies; never grant new families implicitly."""

from typing import Any

SUPPORTED_KINDS = (
    "tcp_reality",
    "xhttp_reality",
    "grpc_cdn",
    "tcp_reality_ipv6",
    "shadowsocks_ipv6",
    "ws_tls_cdn",
    "xhttp_tls_cdn",
    "trojan_grpc_cdn",
    "vmess_httpupgrade_cdn",
    "trojan_reality_ipv6",
)
LEGACY_DEFAULTS = ("xhttp_reality", "tcp_reality")


def stored_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"profiles": []}
    profiles = value.get("profiles", list(LEGACY_DEFAULTS))
    if not isinstance(profiles, list) or any(not isinstance(p, str) for p in profiles):
        return {"profiles": []}
    return {"profiles": list(dict.fromkeys(p for p in profiles if p in SUPPORTED_KINDS))}
