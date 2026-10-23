"""Build an authenticated REALITY backhaul around the existing foreign SOCKS exit."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


def configurations(
    address: str,
    server_name: str,
    identity: str,
    private_key: str,
    public_key: str,
    short_id: str,
    account: dict[str, str],
    source_address: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not all([address, server_name, identity, private_key, public_key, short_id]):
        raise ValueError("Complete peer identity required")
    if not account.get("user") or not account.get("pass"):
        raise ValueError("Authenticated SOCKS exit required")
    options = component_settings(
        "forward",
        {
            "server_listen": "::",
            "server_port": 24432,
            "exit_port": 19981,
            "client_port": 19987,
            "keepalive_idle_seconds": 30,
            "keepalive_interval_seconds": 10,
            "tcp_user_timeout_ms": 90000,
            "xudp_concurrency": 8,
            "fingerprint": "chrome",
            "reality_target_port": 443,
        },
    )
    mux = {
        "enabled": True,
        "concurrency": -1,
        "xudpConcurrency": options["xudp_concurrency"],
        "xudpProxyUDP443": "allow",
    }
    server: dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": options["server_listen"],
                "port": options["server_port"],
                "tag": "FORWARD_BACKHAUL",
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": identity, "flow": "xtls-rprx-vision"}],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "sockopt": {
                        "tcpKeepAliveIdle": options["keepalive_idle_seconds"],
                        "tcpKeepAliveInterval": options["keepalive_interval_seconds"],
                        "tcpUserTimeout": options["tcp_user_timeout_ms"],
                    },
                    "realitySettings": {
                        "dest": server_name + ":" + str(options["reality_target_port"]),
                        "serverNames": [server_name],
                        "privateKey": private_key,
                        "shortIds": [short_id],
                        "show": False,
                    },
                },
            }
        ],
        "outbounds": [
            {
                "tag": "EXIT",
                "protocol": "socks",
                "mux": deepcopy(mux),
                "settings": {
                    "servers": [
                        {
                            "address": "127.0.0.1",
                            "port": options["exit_port"],
                            "users": [dict(account)],
                        }
                    ]
                },
            }
        ],
    }
    client: dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": options["client_port"],
                "protocol": "socks",
                "settings": {"auth": "password", "accounts": [dict(account)], "udp": True},
            }
        ],
        "outbounds": [
            {
                "tag": "FORWARD",
                "protocol": "vless",
                "mux": deepcopy(mux),
                "settings": {
                    "vnext": [
                        {
                            "address": address,
                            "port": options["server_port"],
                            "users": [
                                {"id": identity, "encryption": "none", "flow": "xtls-rprx-vision"}
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "sockopt": {
                        "tcpKeepAliveIdle": options["keepalive_idle_seconds"],
                        "tcpKeepAliveInterval": options["keepalive_interval_seconds"],
                        "tcpUserTimeout": options["tcp_user_timeout_ms"],
                    },
                    "realitySettings": {
                        "serverName": server_name,
                        "fingerprint": options["fingerprint"],
                        "publicKey": public_key,
                        "shortId": short_id,
                    },
                },
            }
        ],
    }
    if source_address:
        client["outbounds"][0]["sendThrough"] = source_address
    return server, client
