"""Build an authenticated REALITY backhaul around the existing foreign SOCKS exit."""

from copy import deepcopy
from typing import Any


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
    mux = {"enabled": True, "concurrency": -1, "xudpConcurrency": 8, "xudpProxyUDP443": "allow"}
    server: dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "::",
                "port": 24432,
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
                        "tcpKeepAliveIdle": 30,
                        "tcpKeepAliveInterval": 10,
                        "tcpUserTimeout": 90000,
                    },
                    "realitySettings": {
                        "dest": server_name + ":443",
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
                    "servers": [{"address": "127.0.0.1", "port": 19981, "users": [dict(account)]}]
                },
            }
        ],
    }
    client: dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 19987,
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
                            "port": 24432,
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
                        "tcpKeepAliveIdle": 30,
                        "tcpKeepAliveInterval": 10,
                        "tcpUserTimeout": 90000,
                    },
                    "realitySettings": {
                        "serverName": server_name,
                        "fingerprint": "chrome",
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
