from dataclasses import dataclass, replace
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from keyholder.schemas import Policy, ProfileKind


@dataclass(frozen=True)
class Profile:
    kind: ProfileKind
    name: str
    address: str
    port: int
    uuid: str
    sni: str
    host: str
    path: str
    fingerprint: str
    public_key: str = ""
    short_id: str = ""
    ech: str = ""

    @property
    def transport(self) -> str:
        return "ws" if self.kind == "ws_cdn" else "tcp" if self.kind == "tcp_reality" else "xhttp"

    @property
    def security(self) -> str:
        return "reality" if self.kind.endswith("reality") else "tls"

    @property
    def alpn(self) -> list[str]:
        return ["http/1.1"] if self.kind == "ws_cdn" else ["h2", "http/1.1"]

    @property
    def mode(self) -> str:
        return "stream-one" if self.kind == "xhttp_reality" else "stream-up"


def normalize(link: str) -> Profile | None:
    if len(link) > 16384 or any(ord(c) < 32 for c in link):
        return None
    try:
        u = urlsplit(link)
        if u.scheme != "vless" or not u.hostname or not u.port or u.password:
            return None
        uid = str(UUID(u.username or ""))
        q = parse_qs(u.query, max_num_fields=64)

        def get(key: str, default: str = "") -> str:
            values = q.get(key, [default])
            if len(values) != 1:
                raise ValueError("Duplicate parameter")
            return values[0]

        transport, security = get("type", "tcp"), get("security")
        kinds: dict[tuple[str, str], ProfileKind] = {
            ("xhttp", "reality"): "xhttp_reality",
            ("tcp", "reality"): "tcp_reality",
            ("raw", "reality"): "tcp_reality",
            ("xhttp", "tls"): "xhttp_cdn",
            ("ws", "tls"): "ws_cdn",
        }
        kind = kinds.get((transport, security))
        if not kind or get("encryption", "none") != "none":
            return None
        sni = get("sni", u.hostname)
        pbk, sid = get("pbk"), get("sid")
        if security == "reality" and (not pbk or not sni):
            return None
        fields = [u.hostname, sni, get("host"), get("path", "/"), get("fp", "chrome"), pbk, sid]
        if any(len(v) > 2048 or any(ord(c) < 32 for c in v) for v in fields):
            return None
        return Profile(
            kind,
            unquote(u.fragment)[:200] or kind,
            u.hostname,
            u.port,
            uid,
            sni,
            get("host", sni),
            get("path", "/"),
            get("fp", "chrome"),
            pbk,
            sid,
        )
    except (ValueError, UnicodeError):
        return None


def generate_profiles(links: list[str], policy: Policy, ech: str) -> list[Profile]:
    result = []
    if policy.ech_enabled and not ech:
        raise ValueError("ECH configuration missing")
    for link in links:
        profile = normalize(link)
        if not profile or profile.kind not in policy.profiles:
            continue
        if profile.kind != "xhttp_cdn" or policy.include_base_cdn or not policy.ech_enabled:
            result.append(profile)
        if profile.kind == "xhttp_cdn" and policy.ech_enabled:
            result.append(replace(profile, name=profile.name + " ECH", ech=ech))
    return result
