import base64
import json
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from keyholder.rendering.profiles import Profile


class Renderer(Protocol):
    media_type: str

    def render(self, profiles: list[Profile]) -> str: ...


def address_literal(address: str) -> str:
    return f"[{address}]" if ":" in address else address


class URIRenderer:
    media_type = "text/plain"

    def render(self, profiles: list[Profile]) -> str:
        links = []
        for p in profiles:
            host = address_literal(p.address)
            name = quote(p.name, safe="")
            if p.kind == "shadowsocks_ipv6":
                userinfo = (
                    base64.urlsafe_b64encode(f"{p.method}:{p.password}".encode())
                    .decode()
                    .rstrip("=")
                )
                links.append(f"ss://{userinfo}@{host}:{p.port}#{name}")
                continue
            if p.protocol == "vmess" and not p.ech_config_list:
                payload = {
                    "v": "2",
                    "ps": p.name,
                    "add": p.address,
                    "port": str(p.port),
                    "id": p.uuid,
                    "aid": "0",
                    "scy": p.cipher,
                    "net": p.transport,
                    "type": "none",
                    "host": p.host,
                    "path": p.path,
                    "tls": "tls",
                    "sni": p.sni,
                    "alpn": "http/1.1",
                }
                links.append("vmess://" + base64.b64encode(json.dumps(payload).encode()).decode())
                continue
            q = {
                "encryption": "none",
                "type": p.transport,
                "security": p.security,
                "sni": p.sni,
                "fp": p.fingerprint,
            }
            if p.ech_config_list:
                q["ech"] = p.ech_config_list
            if p.protocol == "vmess":
                q["encryption"] = p.cipher
            if p.security == "reality":
                q.update(pbk=p.public_key, sid=p.short_id)
                if p.spider_x:
                    q["spx"] = p.spider_x
            if p.alpn:
                q["alpn"] = ",".join(p.alpn)
            if p.transport == "xhttp":
                q.update(host=p.host, path=p.path, mode=p.mode)
            if p.transport in {"ws", "httpupgrade"}:
                q.update(host=p.host, path=p.path)
            if p.transport == "grpc":
                q.update(serviceName=p.service_name, mode=p.mode)
                if p.authority:
                    q["authority"] = p.authority
            if p.flow:
                q["flow"] = p.flow
            if p.protocol == "trojan":
                q.pop("encryption", None)
            credential = quote(p.password, safe="") if p.protocol == "trojan" else p.uuid
            links.append(f"{p.protocol}://{credential}@{host}:{p.port}?{urlencode(q)}#{name}")
        if not links:
            raise ValueError("No compatible profiles")
        return base64.b64encode(("\n".join(links) + "\n").encode()).decode()


class XrayRenderer:
    media_type = "application/json"

    def render(self, profiles: list[Profile]) -> str:
        configs = []
        for p in profiles:
            if p.kind == "shadowsocks_ipv6":
                outbound: dict[str, Any] = {
                    "tag": "proxy",
                    "protocol": "shadowsocks",
                    "settings": {
                        "servers": [
                            {
                                "address": p.address,
                                "port": p.port,
                                "method": p.method,
                                "password": p.password,
                            }
                        ]
                    },
                    "mux": {"enabled": False},
                }
            else:
                user = {"id": p.uuid, "encryption": "none"}
                if p.flow:
                    user["flow"] = p.flow
                stream: dict[str, Any] = {
                    "network": "tcp" if p.transport == "raw" else p.transport,
                    "security": p.security,
                }
                tls: dict[str, Any] = {"serverName": p.sni, "fingerprint": p.fingerprint}
                if p.alpn:
                    tls["alpn"] = list(p.alpn)
                if p.security == "reality":
                    tls.update(publicKey=p.public_key, shortId=p.short_id)
                    if p.spider_x:
                        tls["spiderX"] = p.spider_x
                    stream["realitySettings"] = tls
                else:
                    tls["allowInsecure"] = False
                    if p.ech_config_list:
                        tls["echConfigList"] = p.ech_config_list
                    stream["tlsSettings"] = tls
                if p.transport == "xhttp":
                    stream["xhttpSettings"] = {"host": p.host, "path": p.path, "mode": p.mode}
                elif p.transport == "ws":
                    ws: dict[str, Any] = {"path": p.path}
                    if p.host:
                        ws["headers"] = {"Host": p.host}
                    stream["wsSettings"] = ws
                elif p.transport == "httpupgrade":
                    stream["httpupgradeSettings"] = {"host": p.host, "path": p.path}
                elif p.transport == "grpc":
                    grpc: dict[str, Any] = {
                        "serviceName": p.service_name,
                        "multiMode": p.mode == "multi",
                    }
                    if p.authority:
                        grpc["authority"] = p.authority
                    stream["grpcSettings"] = grpc
                outbound = {
                    "tag": "proxy",
                    "protocol": "vless",
                    "settings": {
                        "vnext": [{"address": p.address, "port": p.port, "users": [user]}]
                    },
                    "streamSettings": stream,
                    "mux": {"enabled": False},
                }
                if p.protocol == "trojan":
                    outbound["protocol"] = "trojan"
                    outbound["settings"] = {
                        "servers": [{"address": p.address, "port": p.port, "password": p.password}]
                    }
                elif p.protocol == "vmess":
                    outbound["protocol"] = "vmess"
                    outbound["settings"]["vnext"][0]["users"] = [
                        {"id": p.uuid, "alterId": 0, "security": p.cipher}
                    ]
            configs.append(
                {
                    "remarks": p.name,
                    "inbounds": [
                        {
                            "tag": "socks",
                            "listen": "127.0.0.1",
                            "port": 10808,
                            "protocol": "socks",
                            "settings": {"udp": True},
                        }
                    ],
                    "outbounds": [outbound],
                }
            )
        if not configs:
            raise ValueError("No compatible profiles")
        return json.dumps(configs, ensure_ascii=False)


def select_renderer(output: str | None, user_agent: str) -> Renderer:
    # JSON import is opt-in; client version is never guessed from its name.
    if output == "xray" or (output is None and "keyholder-xray" in user_agent.lower()):
        return XrayRenderer()
    return URIRenderer()
