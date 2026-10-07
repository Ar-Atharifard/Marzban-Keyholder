import base64
import json
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from keyholder.rendering.profiles import Profile


class Renderer(Protocol):
    media_type: str

    def render(self, profiles: list[Profile]) -> str: ...


class URIRenderer:
    media_type = "text/plain"

    def render(self, profiles: list[Profile]) -> str:
        links = []
        for p in profiles:
            q = {
                "encryption": "none",
                "type": p.transport,
                "security": p.security,
                "sni": p.sni,
                "fp": p.fingerprint,
            }
            if p.security == "reality":
                q.update(pbk=p.public_key, sid=p.short_id)
            else:
                q["alpn"] = ",".join(p.alpn)
            if p.transport in {"xhttp", "ws"}:
                q.update(host=p.host, path=p.path)
            if p.transport == "xhttp":
                q["mode"] = p.mode
            if p.kind == "tcp_reality":
                q["flow"] = "xtls-rprx-vision"
            if p.ech:
                # URI ECH import is client-specific; require the Xray JSON renderer.
                continue
            host = f"[{p.address}]" if ":" in p.address else p.address
            links.append(
                f"vless://{p.uuid}@{host}:{p.port}?{urlencode(q)}#{quote(p.name, safe='')}"
            )
        if not links:
            raise ValueError("No profiles supported by renderer")
        return base64.b64encode(("\n".join(links) + "\n").encode()).decode()


class XrayRenderer:
    media_type = "application/json"

    def render(self, profiles: list[Profile]) -> str:
        configs = []
        for p in profiles:
            user = {"id": p.uuid, "encryption": "none"}
            if p.kind == "tcp_reality":
                user["flow"] = "xtls-rprx-vision"
            stream: dict[str, Any] = {"network": p.transport, "security": p.security}
            tls: dict[str, Any] = {"serverName": p.sni, "fingerprint": p.fingerprint}
            if p.security == "reality":
                tls.update(publicKey=p.public_key, shortId=p.short_id)
                stream["realitySettings"] = tls
            else:
                tls.update(alpn=p.alpn, allowInsecure=False)
                if p.ech:
                    tls["echConfigList"] = p.ech
                stream["tlsSettings"] = tls
            if p.transport == "xhttp":
                stream["xhttpSettings"] = {"host": p.host, "path": p.path, "mode": p.mode}
            elif p.transport == "ws":
                stream["wsSettings"] = {"path": p.path, "headers": {"Host": p.host}}
            outbound = {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]},
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
    # Conservative default: clients mentioning v2rayN aren't assumed to support JSON import.
    # Explicit format=xray guarantees static ECH delivery. Future UA rules register here.
    if output == "xray" or (output is None and "keyholder-xray" in user_agent.lower()):
        return XrayRenderer()
    return URIRenderer()
