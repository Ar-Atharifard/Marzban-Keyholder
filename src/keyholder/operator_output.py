"""Standard-library presentation for operators; never changes API/JSON values.

Also installed beside the standalone Telegram bot as operator_output.py. Keep this
module compatible with the supported Ubuntu host's Python 3.10.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from decimal import Decimal, InvalidOperation
from typing import Any

LABELS = {
    "id": "ID",
    "local_status": "Subscription delivery",
    "status": "Status",
    "created_at": "Created",
    "updated_at": "Updated",
    "checked_at": "Checked",
    "sampled_at": "Sampled",
    "quota_bytes": "Purchased traffic",
    "username": "Panel username",
    "name": "Name",
    "data_limit": "Traffic allowance",
    "used_traffic": "Traffic used",
    "expire": "Expires",
    "usages": "Traffic by node",
    "node_id": "Node ID",
    "node_name": "Node",
    "quota_gb": "Traffic allowance",
    "remaining_bytes": "Remaining quota",
    "memory_available_mib": "Available RAM",
    "memory_total_mib": "Total RAM",
    "load_1_5_15": "Load average (1 / 5 / 15 minutes)",
    "cpu_busy_percent": "CPU busy",
    "cpus": "CPU cores",
    "uptime_seconds": "Uptime",
    "received_bytes": "Network received",
    "sent_bytes": "Network sent",
    "conntrack_entries": "Tracked connections",
    "conntrack_limit": "Connection tracking limit",
    "inbounds": "Selected inbounds",
    "mapping": "Panel mapping",
    "upstream_username": "Panel username",
    "backend_id": "Backend ID",
    "customer_id": "Customer ID",
    "notification_state": "Notifications",
    "first_seen": "First observed",
    "last_seen": "Last observed",
    "guidance": "Next step",
    "acks": "Acknowledged incidents",
    "silences": "Silenced until",
    "disabled_rules": "Disabled notification rules",
    "entry_permitted": "Customer entry permitted",
    "percent": "Budget used",
    "tls": "TLS",
    "ech": "ECH enabled",
    "api_url": "API URL",
    "foreign_keys": "Database relationships valid",
    "duration_days": "Purchased duration",
    "amount": "Amount",
    "referrer_id": "Referrer ID",
    "payment_id": "Payment ID",
    "purchase_id": "Purchase ID",
    "referral_ids": "Referral IDs",
    "gift_id": "Gift ID",
    "usage": "Usage",
    "api_container": "API container",
    "notification_error": "Notification delivery error",
    "size_bytes": "Size",
    "media_type": "File type",
    "disk_used_gib": "Disk used",
    "disk_total_gib": "Disk capacity",
    "disk_free_gib": "Disk free",
    "swap_used_mib": "Swap used",
    "swap_total_mib": "Swap capacity",
    "heartbeat_age_seconds": "Time since panel heartbeat",
    "rule": "Notification rule",
    "key": "Incident / request key",
}
BYTE_FIELDS = {"data_limit", "used_traffic", "size", "bytes"}
TIME_FIELDS = {"expire", "expires", "first_seen", "last_seen", "sampled_at", "since", "until"}
MONEY_FIELDS = {
    "amount",
    "paid",
    "outstanding",
    "refunded",
    "allocated",
    "unallocated",
    "confirmed",
    "net",
    "available",
    "total",
    "payments",
    "purchases",
}
# These are implementation counters, not useful operator measurements.
INTERNAL_FIELDS = {"cpu_total_ticks", "cpu_idle_ticks", "signature", "alert_contract_version"}
SECRET_FIELDS = {
    "token_hash",
    "token_encrypted",
    "api_key",
    "admin_key",
    "secret",
    "access_token",
    "refresh_token",
    "token",
    "subscription_url",
    "config_uri",
    "panel_url",
    "password",
    "content",
}


def byte_count(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024 or unit == "PiB":
            return f"{value:,.0f} B" if unit == "B" else f"{value:,.2f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def duration(seconds: float) -> str:
    remaining = max(0, int(seconds))
    parts = []
    for divisor, unit in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        amount, remaining = divmod(remaining, divisor)
        if amount:
            parts.append(f"{amount:,} {unit}{'s' if amount != 1 else ''}")
    return " ".join(parts) or "0 seconds"


def timestamp(value: Any) -> str:
    try:
        if isinstance(value, (int, float)):
            parsed = dt.datetime.fromtimestamp(value, dt.timezone.utc)  # noqa: UP017
        else:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)  # noqa: UP017
        return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")  # noqa: UP017
    except (ValueError, OverflowError, OSError):
        return "Invalid date"


def label(key: str) -> str:
    # Preserve exact keys used by ack/silence/rule commands and protocol tags.
    if key.isupper() or ":" in key or "." in key or "-" in key:
        return key
    return LABELS.get(key, key.replace("_", " ").capitalize())


def scalar(value: Any, key: str, context: dict[str, Any]) -> str:
    if value is None:
        return "None" if key == "notification_error" else "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return "Not available"
        if key in {"id", "port"} or key.endswith("_id"):
            return str(value)
        if key == "expire":
            if value == 0:
                return "Awaiting activation" if context.get("status") == "on_hold" else "No expiry"
            return timestamp(value)
        if key in TIME_FIELDS:
            return timestamp(value)
        if key == "data_limit" and value == 0:
            return "Unlimited"
        if key.endswith("_bytes") or key in BYTE_FIELDS:
            return byte_count(value)
        if key == "quota_gb":
            return "Unlimited" if value == 0 else byte_count(value * 1024**3)
        if key.endswith("_seconds"):
            return duration(value)
        if key.endswith("_hours"):
            return duration(value * 3600)
        if key.endswith("_days") or key == "days":
            return "No expiry" if key == "days" and value == 0 else f"{value:,} days"
        for suffix, unit in (("_percent", "%"), ("_mib", " MiB"), ("_gib", " GiB")):
            if key.endswith(suffix):
                return f"{value:,.2f}{unit}"
        if key == "percent":
            return f"{value:,.1f}%"
    if key in MONEY_FIELDS and context.get("currency"):
        try:
            amount = Decimal(str(value))
            if amount.is_finite():
                unit = "toman" if context.get("unit") == "toman" else str(context["currency"])
                return f"{amount:,f} {unit}"
        except InvalidOperation:
            pass
    if isinstance(value, (int, float)):
        return f"{value:,}"
    if key.endswith("_at") or key in TIME_FIELDS | {"last_check", "cpu_sampled_at"}:
        return timestamp(value)
    if key == "notification_error":
        return {
            "TimeoutError": "Telegram or heartbeat request timed out",
            "URLError": "Could not connect to Telegram or heartbeat endpoint",
            "HTTPError": "Telegram or heartbeat endpoint returned an HTTP error",
            "ValueError": "Notification configuration or endpoint response is invalid",
        }.get(str(value), "Delivery failed; inspect the monitor service journal")
    if key in {"notification_state", "status", "state", "profile_source"}:
        return str(value).replace("_", " ")
    return str(value) or "None"


def render(value: Any, key: str = "") -> str:
    """Render every result recursively, keeping IDs/tags and exact money intact."""

    def lines(item: Any, field: str, indent: int, context: dict[str, Any]) -> list[str]:
        pad = "  " * indent
        if isinstance(item, dict):
            rows = []
            local = {**context, **item}
            if field in {"IRR", "USDT", "LTC"}:
                local["currency"] = field
            for name, contents in item.items():
                if name in INTERNAL_FIELDS or name in SECRET_FIELDS:
                    continue
                if name == "alerts" and item.get("incidents"):
                    continue
                title = label(str(name))
                if isinstance(contents, (dict, list)) and contents:
                    rows.append(f"{pad}{title}:")
                    rows.extend(lines(contents, str(name), indent + 1, local))
                else:
                    display = (
                        timestamp(contents)
                        if field == "silences" and contents is not None
                        else scalar(contents, str(name), local)
                        if not isinstance(contents, (dict, list))
                        else "None"
                    )
                    rows.append(f"{pad}{title}: {display}")
            # Only an explicit account quota supports remaining/percentage calculations.
            # Per-node /usage counters do not contain a plan and must not invent one.
            if "data_limit" in item and "used_traffic" in item:
                used, limit = item["used_traffic"], item["data_limit"]
                remaining = "Not available"
                if isinstance(limit, (int, float)) and limit >= 0:
                    if limit == 0:
                        remaining = "Unlimited"
                    elif isinstance(used, (int, float)) and used >= 0:
                        remaining = byte_count(max(0, limit - used))
                        rows.append(f"{pad}Quota used: {100 * used / limit:.1f}%")
                rows.append(f"{pad}Remaining quota: {remaining}")
            if isinstance(item.get("expire"), (int, float)) and item["expire"] > 0:
                seconds = item["expire"] - time.time()
                rows.append(
                    f"{pad}Time remaining: {duration(seconds) if seconds > 0 else 'Expired'}"
                )
            return rows or [pad + "None"]
        if isinstance(item, list):
            if field == "load_1_5_15":
                return [pad + " / ".join(f"{x:.2f}" for x in item)]
            rows = []
            for number, entry in enumerate(item, 1):
                if isinstance(entry, (dict, list)):
                    rows.append(f"{pad}{number}.")
                    rows.extend(lines(entry, field, indent + 1, context))
                else:
                    rows.append(f"{pad}• {scalar(entry, field, context)}")
            return rows or [pad + "None"]
        return [pad + scalar(item, field, context)]

    return "\n".join(lines(value, key, 0, {}))
