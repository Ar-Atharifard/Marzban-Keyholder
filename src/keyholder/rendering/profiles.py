import base64
import binascii
import ipaddress
import json
import re
from dataclasses import dataclass, replace
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
    protocol: str = "vless"
    cipher: str = "auto"
    ech_config_list: str = ""


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


# Published Cloudflare edge ranges: https://www.cloudflare.com/ips-v6
# Never use this exception for arbitrary direct/origin IP destinations.
CLOUDFLARE_IPV6 = tuple(
    ipaddress.ip_network(prefix)
    for prefix in (
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def cloudflare_ipv6(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 6 and any(ip in network for network in CLOUDFLARE_IPV6)


def allowed_cdn(profile: Profile, allowed_hosts: tuple[str, ...]) -> bool:
    """Permit DNS CDN hosts or trusted Cloudflare IPv6 edges with an allowed TLS/HTTP identity."""
    if profile.security != "tls":
        return True
    if cloudflare_ipv6(profile.address):
        if not allowed_hosts or profile.sni not in allowed_hosts:
            return False
        identity = profile.authority if profile.transport == "grpc" else profile.host
        return identity == profile.sni
    return not allowed_hosts or profile.address in allowed_hosts


def normalize(link: str) -> Profile | None:
    """Normalize supported links; omit unsupported or malformed links."""
    if len(link) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in link):
        return None
    try:
        if link.startswith("vmess://"):
            return normalize_vmess(link)
        if link.startswith("trojan://"):
            return normalize_trojan(link)
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
            try:
                ipaddress.ip_address(u.hostname)
            except ValueError:
                kind = "grpc_cdn"
            else:
                if not cloudflare_ipv6(u.hostname):
                    return None
                kind = "grpc_cdn"
        elif security == "tls" and transport in {"ws", "xhttp"}:
            # Accept only DNS names or published Cloudflare IPv6 edges, never an origin IP.
            try:
                ipaddress.ip_address(u.hostname)
            except ValueError:
                kind = "ws_tls_cdn" if transport == "ws" else "xhttp_tls_cdn"
            else:
                if not cloudflare_ipv6(u.hostname):
                    return None
                kind = "ws_tls_cdn" if transport == "ws" else "xhttp_tls_cdn"
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
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
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
    if (
        method not in {"aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305"}
        or not separator
        or not password
    ):
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


def apply_cdn_ech(
    profiles: list[Profile], config: str, allowed_hosts: tuple[str, ...]
) -> list[Profile]:
    """Apply trusted delivery settings only to explicitly permitted CDN TLS hosts."""
    if not config:
        return profiles
    return [
        replace(p, ech_config_list=config, fingerprint="chrome")
        if p.security == "tls" and p.address in allowed_hosts and p.sni in allowed_hosts
        else p
        for p in profiles
    ]


def normalize_trojan(link: str) -> Profile | None:
    u = urlsplit(link)
    if not u.hostname or not u.port or u.password or u.path not in {"", "/"}:
        return None
    password = text(unquote(u.username or "", errors="strict"), 1024)
    if not password:
        return None
    # Reuse the strict TLS/REALITY transport parser, never import arbitrary settings.
    endpoint = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    synthetic = f"vless://00000000-0000-4000-8000-000000000000@{endpoint}:{u.port}"
    parsed = normalize(synthetic + "?" + u.query + "#" + u.fragment)
    if parsed is None:
        return None
    if parsed.security == "tls" and parsed.transport == "grpc":
        try:
            ipaddress.ip_address(parsed.address)
        except ValueError:
            kind: ProfileKind = "trojan_grpc_cdn"
        else:
            if not cloudflare_ipv6(parsed.address):
                return None
            kind = "trojan_grpc_cdn"
    elif parsed.security == "reality" and parsed.transport in {"tcp", "raw"}:
        if not destination(parsed.address):
            return None
        kind = "trojan_reality_ipv6"
    else:
        return None
    return replace(parsed, kind=kind, protocol="trojan", password=password, uuid="", flow="")


def normalize_vmess(link: str) -> Profile | None:
    if "@" in link and "?" in link:
        u = urlsplit(link)
        if not u.hostname or not u.port or u.password or u.path not in {"", "/"}:
            return None
        q = parse_qs(u.query, keep_blank_values=True, max_num_fields=64, errors="strict")
        if any(len(v) != 1 for v in q.values()):
            return None
        params = {k: text(v[0]) for k, v in q.items()}
        if any(params.get(k, "0") != "0" for k in ("insecure", "allowInsecure")):
            return None
        # Current v2rayNG imports ECH only through standard URI query parameters.
        # Upstream ECH is still ignored; only the operator's trusted setting is used.
        payload = {
            "add": u.hostname,
            "port": u.port,
            "id": unquote(u.username or ""),
            "net": params.get("type"),
            "tls": params.get("security"),
            "ps": unquote(u.fragment),
            "sni": params.get("sni"),
            "host": params.get("host", ""),
            "path": params.get("path", "/"),
            "scy": params.get("encryption", "auto"),
        }
        return normalize_vmess("vmess://" + base64.b64encode(json.dumps(payload).encode()).decode())
    data = json.loads(decode_base64(link[8:]).decode("utf-8"))
    if not isinstance(data, dict):
        return None
    address = text(str(data.get("add", "")), 253)
    destination(address)
    try:
        ipaddress.ip_address(address)
    except ValueError:
        pass
    else:
        if not cloudflare_ipv6(address):
            return None
    port = int(data.get("port", 0))
    if not 1 <= port <= 65535:
        return None
    if data.get("tls") != "tls" or data.get("net") != "httpupgrade":
        return None
    if int(data.get("aid", 0)) != 0 or data.get("allowInsecure") not in {None, False, "0"}:
        return None
    cipher = data.get("scy", "auto")
    if cipher not in {"auto", "aes-128-gcm", "chacha20-poly1305"}:
        return None
    sni = text(str(data.get("sni") or address), 253)
    destination(sni)
    return Profile(
        kind="vmess_httpupgrade_cdn",
        protocol="vmess",
        cipher=cipher,
        name=text(str(data.get("ps") or "VMess HTTPUpgrade"), 200),
        address=address,
        port=port,
        transport="httpupgrade",
        security="tls",
        uuid=str(UUID(str(data.get("id", "")))),
        sni=sni,
        host=text(str(data.get("host", ""))),
        path=text(str(data.get("path") or "/")),
        alpn=("http/1.1",),
    )
