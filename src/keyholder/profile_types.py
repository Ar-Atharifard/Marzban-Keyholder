"""One authoritative supported-family list and legacy-compatible defaults."""

from typing import Literal, get_args

ProfileKind = Literal[
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
    "trojan_xhttp_cdn",
    "grpc_reality",
]

SUPPORTED_KINDS: tuple[str, ...] = get_args(ProfileKind)
DEFAULT_PROFILES: tuple[ProfileKind, ...] = (
    "tcp_reality",
    "xhttp_reality",
    "grpc_cdn",
    "tcp_reality_ipv6",
    "shadowsocks_ipv6",
)
