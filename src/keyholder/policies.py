"""Conservative read compatibility for stored policies; never grant new families implicitly."""

from typing import Any

from keyholder.profile_types import SUPPORTED_KINDS as SUPPORTED_KINDS

LEGACY_DEFAULTS = ("xhttp_reality", "tcp_reality")


def stored_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"profiles": []}
    profiles = value.get("profiles", list(LEGACY_DEFAULTS))
    if not isinstance(profiles, list) or any(not isinstance(p, str) for p in profiles):
        return {"profiles": []}
    return {"profiles": list(dict.fromkeys(p for p in profiles if p in SUPPORTED_KINDS))}
