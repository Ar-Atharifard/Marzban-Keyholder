import base64
import binascii
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from keyholder.schemas import Policy, ProfileKind


@dataclass(frozen=True, repr=False)
class Profile:
    kind: ProfileKind
    name: str
    address: str
    port: int
    transport: str
    security: str
    uuid: str = ""
    sni: str = ""
    host: str = ""
    path: str = "/"
    fingerprint: str = "chrome"
    public_key: str = ""
    short_id: str = ""
    flow: str = ""
    mode: str = ""
    alpn: tuple[str, ...] = ()
    service_name: str = ""
    authority: str = ""
    spider_x: str = ""
    method: str = ""
    password: str = ""


def decode_base64(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]+", value):
        raise ValueError("Invalid base64")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def text(value: str, maximum: int = 2048) -> str:
    if len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid text")
    return value


def destination(address: str) -> bool:
    """Validate a hostname or IP literal and return whether it is IPv6; never resolve DNS."""
    try:
        return ipaddress.ip_address(address).version == 6
    except ValueError:
        if ":" in address or "%" in address:
            raise ValueError("Invalid address") from None
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", address):
            raise ValueError("Invalid hostname") from None
        return False


def normalize(link: str) -> Profile | None:
    """Normalize supported links; omit unsupported or malformed links."""
    if len(link) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in link):
        return None
    try:
        if link.startswith("ss://"):
            return normalize_shadowsocks(link)
        u = urlsplit(link)
        if u.scheme != "vless" or not u.hostname or not u.port or u.password:
            return None
        if u.path not in {"", "/"}:
            return None
        uid = str(UUID(unquote(u.username or "", errors="strict")))
        ipv6 = destination(u.hostname)
        q = parse_qs(u.query, keep_blank_values=True, max_num_fields=64, errors="strict")

        def get(key: str, default: str = "") -> str:
            values = q.get(key, [default])
            if len(values) != 1:
                raise ValueError("Duplicate parameter")
            return text(values[0])

        transport, security = get("type", "tcp"), get("security")
        if get("encryption", "none") != "none":
            return None
        if security == "reality" and transport in {"tcp", "raw"}:
            kind: ProfileKind = "tcp_reality_ipv6" if ipv6 else "tcp_reality"
        elif security == "reality" and transport == "xhttp":
            kind = "xhttp_reality"
        elif security == "tls" and transport == "grpc":
            kind = "grpc_cdn"
        elif security == "tls" and transport in {"ws", "xhttp"}:
            # CDN profiles must use DNS names, never a literal origin IP.
            try:
                ipaddress.ip_address(u.hostname)
            except ValueError:
                kind = "ws_tls_cdn" if transport == "ws" else "xhttp_tls_cdn"
            else:
                return None
        else:
            return None
        sni = get("sni", u.hostname)
        destination(sni)
        fingerprint = get("fp", "chrome")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fingerprint):
            return None
        public_key, short_id = "", ""
        if security == "reality":
            public_key, short_id = get("pbk"), get("sid")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", public_key):
                return None
            if len(decode_base64(public_key)) != 32:
                return None
            if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,8}", short_id):
                return None
        flow = get("flow") if transport in {"tcp", "raw"} else ""
        if flow not in {"", "xtls-rprx-vision"}:
            return None
        mode = get("mode", "stream-one") if transport == "xhttp" else ""
        if transport == "xhttp" and mode not in {"auto", "stream-one", "stream-up", "packet-up"}:
            return None
        grpc_mode = get("mode", "gun") if transport == "grpc" else ""
        if transport == "grpc" and grpc_mode not in {"gun", "multi"}:
            return None
        alpn = tuple(get("alpn").split(",")) if get("alpn") else ()
        if any(not re.fullmatch(r"[A-Za-z0-9./_-]{1,32}", a) for a in alpn):
            return None
        # Never import arbitrary extra JSON, ECH, MUX or incompatible flows.
        return Profile(
            kind=kind,
            name=text(unquote(u.fragment, errors="strict"), 200) or kind,
            address=u.hostname,
            port=u.port,
            transport=transport,
            security=security,
            uuid=uid,
            sni=sni,
            fingerprint=fingerprint,
            public_key=public_key,
            short_id=short_id,
            flow=flow,
            alpn=alpn,
            host=get("host") if transport in {"xhttp", "ws"} else "",
            path=get("path", "/") if transport in {"xhttp", "ws"} else "/",
            mode=mode or grpc_mode,
            service_name=get("serviceName") if transport == "grpc" else "",
            authority=get("authority") if transport == "grpc" else "",
            spider_x=get("spx") if security == "reality" else "",
        )
    except (ValueError, UnicodeError, binascii.Error):
        return None


def normalize_shadowsocks(link: str) -> Profile | None:
    # SIP002 userinfo: URL-safe or standard base64, or percent-encoded plaintext.
    payload, _, fragment = link[5:].partition("#")
    if "@" not in payload:
        if "?" in payload:
            return None
        decoded = decode_base64(payload).decode("utf-8")
        return (
            normalize_shadowsocks("ss://" + decoded + ("#" + fragment if fragment else ""))
            if "@" in decoded
            else None
        )
    raw_userinfo, endpoint = payload.rsplit("@", 1)
    u = urlsplit("ss://" + endpoint)
    if not u.hostname or not u.port or u.path not in {"", "/"}:
        return None
    if not destination(u.hostname):
        return None
    params = parse_qs(u.query, keep_blank_values=True, max_num_fields=16)
    if params:
        return None
    decoded = unquote(raw_userinfo, errors="strict")
    if ":" not in decoded:
        decoded = decode_base64(decoded).decode("utf-8")
    method, separator, password = decoded.partition(":")
    if method != "aes-128-gcm" or not separator or not password:
        return None
    text(password, 1024)
    return Profile(
        kind="shadowsocks_ipv6",
        name=text(unquote(fragment, errors="strict"), 200) or "Shadowsocks",
        address=u.hostname,
        port=u.port,
        transport="tcp",
        security="none",
        method=method,
        password=password,
    )


def generate_profiles(links: list[str], policy: Policy) -> list[Profile]:
    return [p for link in links if (p := normalize(link)) is not None and p.kind in policy.profiles]
