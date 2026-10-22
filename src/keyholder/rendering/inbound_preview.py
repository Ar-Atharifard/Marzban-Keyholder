"""Preview delivery names without exporting customer credentials."""

from typing import Any
from urllib.parse import quote, urlencode

from keyholder.config import Settings
from keyholder.rendering.profiles import Profile, delivery_profiles, normalize


def host_profiles(
    inbound: dict[str, Any],
    host: dict[str, Any],
    settings: Settings,
    account_key: str,
    actual: Profile | None = None,
) -> list[str] | None:
    if actual is not None:
        return [p.name for p in delivery_profiles([actual], settings, account_key)]
    # Only static templates can be predicted without Marzban's runtime variables.
    address = str(host.get("address") or "")
    address = (
        address.replace("{SERVER_IP}", "192.0.2.1")
        .replace("{SERVER_IPV6}", "2001:db8::1")
        .strip("[]")
    )
    if host.get("allowinsecure"):
        return []
    name = str(host["remark"]).replace("{USERNAME}", account_key.split("/", 1)[-1])
    if not address or any(c in address + name for c in "{}*"):
        return None
    security = host.get("security")
    if security in {None, "inbound_default"}:
        security = inbound.get("tls", "none")
    # Dummy credentials are used only to reuse the subscription's strict classifier.
    endpoint = f"[{address}]" if ":" in address else address
    params = {
        "security": security,
        "type": inbound.get("network", "tcp"),
        "sni": host.get("sni") or address,
        "pbk": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    }
    identity = str(host.get("host") or "")
    if host.get("use_sni_as_host"):
        identity = str(params["sni"])
    params.update(host=identity, authority=identity)
    protocol = inbound.get("protocol", "vless")
    query = urlencode(params)
    link = (
        f"{protocol}://00000000-0000-4000-8000-000000000000@{endpoint}:443"
        f"?{query}#{quote(name, safe='')}"
    )
    profile = normalize(link, settings.allowed_cdn_networks)
    if profile is None:
        return None
    return [p.name for p in delivery_profiles([profile], settings, account_key)]
