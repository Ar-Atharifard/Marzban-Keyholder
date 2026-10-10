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
            q = {
                "encryption": "none",
                "type": p.transport,
                "security": p.security,
                "sni": p.sni,
                "fp": p.fingerprint,
            }
            if p.security == "reality":
                q.update(pbk=p.public_key, sid=p.short_id)
                if p.spider_x:
                    q["spx"] = p.spider_x
            if p.alpn:
                q["alpn"] = ",".join(p.alpn)
            if p.transport == "xhttp":
                q.update(host=p.host, path=p.path, mode=p.mode)
            if p.transport == "grpc":
                q.update(serviceName=p.service_name, mode=p.mode)
                if p.authority:
                    q["authority"] = p.authority
            if p.flow:
                q["flow"] = p.flow
            links.append(f"vless://{p.uuid}@{host}:{p.port}?{urlencode(q)}#{name}")
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
                    stream["tlsSettings"] = tls
                if p.transport == "xhttp":
                    stream["xhttpSettings"] = {"host": p.host, "path": p.path, "mode": p.mode}
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
