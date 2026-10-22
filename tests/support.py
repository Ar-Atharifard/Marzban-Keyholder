"""Synthetic data and small helpers shared by tests; no production configuration."""

import base64
import json
from typing import Any

from fastapi.testclient import TestClient

ADMIN_KEY = "test-admin-" + "a" * 48
UUID = "12345678-1234-4234-9234-123456789abc"
PBK = "A" * 43
LINK = f"vless://{UUID}@192.0.2.1:9443?type=xhttp&security=reality&sni=direct.example&host=direct.example&path=%2Fx&pbk={PBK}&sid=abcd&extra=malformed&flow=xtls-rprx-vision#Direct"


IPV6 = "2001:db8::1"
PASSWORD = "sanitized:+/=@password"
TCP = f"vless://{UUID}@192.0.2.1:8443?type=tcp&security=reality&pbk={PBK}&sid=aB12&sni=direct.example&fp=firefox&flow=xtls-rprx-vision&spx=%2Fhello#IPv4"
TCP6 = TCP.replace("192.0.2.1:8443", f"[{IPV6}]:10443").replace("type=tcp", "type=raw")
GRPC = f"vless://{UUID}@titan.example:443?type=grpc&security=tls&sni=tls.example&serviceName=service%2Fname%3Fx%3D1&authority=grpc.example&mode=multi&alpn=h2%2Chttp%2F1.1&fp=chrome&flow=xtls-rprx-vision&pbk=invalid&ech=ignored#Titan"
SS = (
    "ss://"
    + base64.urlsafe_b64encode(f"aes-128-gcm:{PASSWORD}".encode()).decode().rstrip("=")
    + f"@[{IPV6}]:10444#IPv6%20SS"
)
ALL = [TCP, LINK, GRPC, TCP6, SS]
KINDS = ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]


class FakeBackend:
    async def configurations(self, username: str) -> list[str]:
        return [LINK]


HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}
ECH = "cloudflare-ech.com+https://8.8.8.8/dns-query"
CDN_HOSTS = ("titan.example",)
AVAILABLE = {"vless": [{"tag": "A"}, {"tag": "C"}], "trojan": [{"tag": "B"}]}
INBOUND_HOSTS = {tag: [{"remark": tag}] for tag in "ABC"}


def create(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/admin/customers", headers=HEADERS, json={"name": "Customer", "upstream_username": "alice"}
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def vmess(address: str = "titan.example") -> str:
    data = {
        "add": address,
        "port": "443",
        "id": UUID,
        "aid": "0",
        "scy": "auto",
        "net": "httpupgrade",
        "tls": "tls",
        "host": "titan.example",
        "path": "/upgrade",
        "sni": "titan.example",
    }
    return "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()


def domestic_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        {
            "inbounds": [{"tag": "foreign"}],
            "outbounds": [
                {"tag": "DIRECT", "protocol": "freedom"},
                {"tag": "BLOCK", "protocol": "blackhole"},
            ],
            "routing": {
                "domainStrategy": "IPIfNonMatch",
                "rules": [{"ip": ["geoip:ir"], "outboundTag": "BLOCK"}],
            },
        },
        {
            "tag": "domestic",
            "listen": "127.0.0.1",
            "streamSettings": {
                "security": "reality",
                "network": "tcp",
                "realitySettings": {"publicKey": "test-public-key"},
            },
        },
        {
            "tag": "TUNNEL",
            "protocol": "socks",
            "settings": {
                "servers": [{"address": "127.0.0.1", "users": [{"user": "infra", "pass": "test"}]}]
            },
        },
    )
