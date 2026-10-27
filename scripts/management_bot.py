#!/usr/bin/env python3
"""Small allowlisted Telegram management client for the host dispatcher."""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import queue
import re
import secrets
import shlex
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any


def readable_result(value: Any, key: str = "") -> str:
    """Human display only; dispatcher results retain their machine-readable units."""
    if isinstance(value, dict):
        rows = [
            f"{str(k).replace('_', ' ').capitalize()}: {readable_result(v, str(k))}"
            for k, v in value.items()
        ]
        used, limit = value.get("used_traffic"), value.get("data_limit")
        if isinstance(used, (int, float)) and (limit is None or isinstance(limit, (int, float))):
            rows.append(
                "Remaining quota: "
                + (
                    readable_result(max(0, limit - used), "remaining_bytes")
                    if limit
                    else "Unlimited"
                )
            )
        return "\n".join(rows) or "None"
    if isinstance(value, list):
        return "\n".join("• " + readable_result(v, key) for v in value) or "None"
    if value is None:
        return "Unlimited" if key in {"expire", "data_limit"} else "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        if key == "expire":
            return (
                dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime(  # noqa: UP017
                    "%Y-%m-%d %H:%M UTC"
                )
                if value
                else "Unlimited"
            )
        if key.endswith("_bytes") or key in {"used_traffic", "data_limit"}:
            if key == "data_limit" and not value:
                return "Unlimited"
            size = float(value)
            for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
                if abs(size) < 1024 or unit == "PiB":
                    return f"{size:,.0f} B" if unit == "B" else f"{size:,.2f} {unit}"
                size /= 1024
        for suffix, unit in (
            ("_percent", "%"),
            ("_mib", " MiB"),
            ("_gib", " GiB"),
            ("_seconds", " seconds"),
        ):
            if key.endswith(suffix):
                return f"{value:,.1f}{unit}"
        if key in {"first_seen", "last_seen", "sampled_at"}:
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime(  # noqa: UP017
                "%Y-%m-%d %H:%M UTC"
            )
        return f"{value:,}"
    return str(value)


MAX_MESSAGE = 3500
SEND_LOCK = threading.Lock()
LAST_SEND = 0.0
TOKEN_PATTERN = re.compile(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}")
BOT_COMMANDS = [
    {"command": "help", "description": "Show the management command reference"},
    {"command": "metrics", "description": "Show RAM, CPU, swap, storage and uptime"},
    {"command": "status", "description": "Show production container status"},
    {"command": "doctor", "description": "Run the complete Keyholder audit"},
    {"command": "monitor", "description": "Show the latest monitoring result"},
    {"command": "alerts", "description": "Show alert bot and timer status"},
    {"command": "customers", "description": "List active customers"},
    {"command": "directory", "description": "Usernames and names only; optional search"},
    {"command": "inbounds", "description": "List all inbounds; add USER to edit a selection"},
    {"command": "users", "description": "List Marzban users"},
    {"command": "link", "description": "Retrieve an existing subscription URL privately"},
    {"command": "configs", "description": "List a customer's connection configurations"},
    {"command": "config", "description": "Retrieve one configuration URI by ID"},
    {"command": "cancel", "description": "Cancel a pending destructive operation"},
]


if TYPE_CHECKING or __package__:
    from scripts import billing_bot
    from scripts.component_config import settings as component_settings
else:
    import billing_bot
    from component_config import settings as component_settings


OPTIONS = component_settings(
    "management_bot",
    {
        "telegram_api_base": "https://api.telegram.org",
        "poll_http_timeout_seconds": 35,
        "request_timeout_seconds": 10,
        "poll_timeout_seconds": 25,
        "dispatch_timeout_seconds": 70,
        "queue_size": 4,
        "poll_batch_size": 10,
        "command_max_age_seconds": 300,
        "confirmation_seconds": 300,
        "send_interval_seconds": 1.05,
        "retry_max_delay_seconds": 30,
        "retry_max_exponent": 5,
    },
)
CONFIRM_SECONDS = OPTIONS["confirmation_seconds"]


def private_state(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("Bot state must be private")
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}


def save_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(value, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def telegram(token: str, method: str, values: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(values).encode()
    request = urllib.request.Request(
        f"{OPTIONS['telegram_api_base'].rstrip('/')}/bot{token}/{method}", data=data, method="POST"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(
            request,
            timeout=OPTIONS["poll_http_timeout_seconds"]
            if method == "getUpdates"
            else OPTIONS["request_timeout_seconds"],
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code != 429 or method != "sendMessage":
            raise
        payload = json.load(error)
        delay = float(payload.get("parameters", {}).get("retry_after", 1))
        if not math.isfinite(delay) or delay < 0 or delay > 30:
            raise ValueError("Telegram rate limit requires a later retry") from None
        time.sleep(delay + 0.1)
        with opener.open(request, timeout=OPTIONS["request_timeout_seconds"]) as response:
            payload = json.load(response)
    if not payload.get("ok"):
        raise RuntimeError("Telegram request failed")
    return payload  # type: ignore[no-any-return]


def dispatch(operation: str, args: dict[str, Any]) -> Any:
    dispatcher = os.getenv(
        "KEYHOLDER_MANAGEMENT_DISPATCHER", "/usr/local/lib/keyholder-admin/host.py"
    )
    payload = json.dumps({"operation": operation, "args": args}).encode()
    result = subprocess.run(
        ["/usr/bin/python3", dispatcher],
        input=payload,
        capture_output=True,
        timeout=OPTIONS["dispatch_timeout_seconds"],
        check=False,
    )
    try:
        envelope = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Administration request failed") from None
    if not envelope.get("ok"):
        raise ValueError(str(envelope.get("error", "Administration request failed")))
    return envelope["result"]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if key not in {"token", "subscription_url", "config_uri", "panel_url", "password"}
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def parse_options(words: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    options: dict[str, str] = {}
    for word in words:
        if "=" not in word:
            positional.append(word)
            continue
        key, value = word.split("=", 1)
        if not re.fullmatch(r"[a-z_]+", key) or key in options:
            raise ValueError("Invalid or duplicate option")
        options[key] = value
    return positional, options


def number(value: str, name: str) -> float:
    try:
        result = float(value)
    except ValueError:
        raise ValueError(f"{name} must be numeric") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def days(value: str) -> int:
    result = number(value, "days")
    if not result.is_integer():
        raise ValueError("days must be a whole number")
    return int(result)


def authorized(message: dict[str, Any], admin_id: int) -> bool:
    return (
        (message.get("chat") or {}).get("type") == "private"
        and (message.get("chat") or {}).get("id") == admin_id
        and (message.get("from") or {}).get("id") == admin_id
    )


def help_text() -> str:
    return """Keyholder management

Inspect
/help — This reference; /start does the same.
/ping — Check that the bot responds.
/metrics — CPU, RAM, swap, disk and uptime.
/status — Container status.
/health — API/database connectivity.
/doctor — Database integrity and integration checks.
/monitor — Latest monitoring results.
/runmonitor — Run checks now without sending alerts.
/alerts — Alert bot and timer status.
/backends — Configured panel/provider namespaces.
/billinghelp — Payments, purchases, referrals, gifts and receipt images.

Customers and links
/users — Marzban accounts, quotas and selections.
/customers [PAGE] [SEARCH] — Customer details; search username/name.
/directory [PAGE] [SEARCH] — Only usernames and private names.
/history [PAGE] — Include revoked registrations.
/show SELECTOR — Customer identity and panel mapping.
/check SELECTOR — Check upstream profile availability.
/usage USER — Plan and traffic counters.
/link SELECTOR — Existing permanent subscription URL.
/configs SELECTOR — List individual configurations and IDs.
/config SELECTOR CONFIG_ID — Retrieve one configuration link.

Inbounds
/inbounds — ALL available inbounds, numbered; [x] marks defaults.
/inbounds USER — Open that user's selection picker.
/select 1,3,5 — Preview a replacement; all/default also work.
Numbers refer to the current list. Defaults apply to future CLI/bot users.

Manage
/create USER quota=20 days=30 inbounds=default — Create panel user and subscription.
Use inbounds=all or 1,3 instead; omitted means default. Zero quota/days = unlimited.
/attach USER — Register an existing panel account; reuse its URL.
Create/attach accept name="Full Name", telegram=@id and phone=+number.
/update USER quota=GB days=N status=active|disabled — Change panel plan/status.
/identity SELECTOR name="Full Name" telegram=@id phone=+number — Edit private identity.
/rename SELECTOR name="Full Name" — Change private name, not panel username.
/setinbounds USER protocol=vless tags=TAG1,TAG2 — Advanced single-protocol selection.
/enable SELECTOR — Resume subscription delivery.
/disable SELECTOR — Pause delivery; downloaded proxies remain usable.
/sync — Register missing panel accounts in Keyholder.
/backup — Make a private local database snapshot.
/resetusage USER — Reset used traffic to zero; confirmation required.
/remap SELECTOR username=NEW — Change panel mapping, keep subscription URL.
/revoke SELECTOR — Permanently revoke subscription delivery.
/rotate SELECTOR — Replace subscription token; old URL stops working.
/confirm CODE — Apply the pending operation within five minutes.
/cancel — Cancel a pending operation or picker.

Alerts
/alertcontrols — Inspect incidents and overrides.
/ack KEY — Acknowledge an alert; does not fix its cause.
/unack KEY — Remove acknowledgement.
/silence KEY hours=24 — Temporarily mute one incident (maximum 168 hours).
/unsilence KEY — Remove that incident's mute.
/rule_disable RULE — Disable a rule; confirmation required.
/rule_enable RULE — Re-enable a rule.

USER = panel username. SELECTOR also accepts quoted private name, ID, phone or Telegram.

Links contain credentials. Retrieve them only in this private administrator chat."""


def planned(command: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"operation": command, "args": args, "expires": time.time() + CONFIRM_SECONDS}


def profile_label(row: dict[str, Any]) -> str:
    names = row.get("generated_names")
    if names is None:
        return "; ".join(row["names"]) + " [preview unavailable]"
    return "; ".join(names) if names else "No compatible profiles (filtered by delivery rules)"


def profile_summary(rows: list[dict[str, Any]]) -> str:
    previews = [row.get("generated_names") for row in rows]
    if any(p is None for p in previews):
        return "Profile total unavailable: one or more host templates cannot be previewed."
    total = sum(len(p) for p in previews if p is not None)
    return f"{len(rows)} inbounds → {total} connection profiles (usage-information row excluded)."


def command(text: str, state: dict[str, Any]) -> str:
    if len(text) > 2048:
        raise ValueError("Command exceeds 2048 characters")
    try:
        words = shlex.split(text, posix=True)
    except ValueError:
        raise ValueError("Invalid quoting") from None
    if not words or not words[0].startswith("/"):
        return help_text()
    name = words.pop(0).split("@", 1)[0].removeprefix("/").lower()
    if name in {
        "purchase",
        "payment",
        "referral",
        "gift",
        "receipt",
        "storage",
        "billing",
        "billinghelp",
    }:
        return billing_bot.command(name, words, state, dispatch, CONFIRM_SECONDS)
    if name == "ping":
        return "Online."
    if name in {"start", "help"}:
        return help_text()
    if name == "inbounds" and not words:
        catalog = dispatch("user-inbounds", {})
        return "\n".join(
            [
                "Available inbounds ([x] default):",
                *[
                    f"{row['number']}. [{'x' if row['selected'] else ' '}] " + profile_label(row)
                    for row in catalog["entries"]
                ],
                "Selected: " + profile_summary([r for r in catalog["entries"] if r["selected"]]),
                "Create with inbounds=1,3 or inbounds=all/default. Omitted means default.",
            ]
        )
    if name == "inbounds" and words:
        if len(words) != 1 or not re.fullmatch(r"[A-Za-z0-9_]{3,32}", words[0]):
            raise ValueError("Usage: /inbounds USER")
        catalog = dispatch("user-inbounds", {"username": words[0]})
        state["picker"] = {**catalog, "expires": time.time() + CONFIRM_SECONDS}
        return "\n".join(
            [
                f"Profiles for {catalog['username']}:",
                *[
                    f"{row['number']}. [{'x' if row['selected'] else ' '}] " + profile_label(row)
                    for row in catalog["entries"]
                ],
                "Selected: " + profile_summary([r for r in catalog["entries"] if r["selected"]]),
                "Reply /select 1,3,5 to replace the selection. /cancel leaves it unchanged.",
            ]
        )
    if name == "select":
        picker = state.get("picker", {})
        if picker.get("expires", 0) < time.time():
            raise ValueError("Picker expired; use /inbounds USER again.")
        choice = "".join(words)
        if choice.lower() in {"all", "default"}:
            defaults = picker.get("default_tags", [])
            rows = [
                row
                for row in picker["entries"]
                if choice.lower() == "all" or row["tag"] in defaults
            ]
            if not rows or (choice.lower() == "default" and len(rows) != len(defaults)):
                raise ValueError("Default selection is empty or unavailable; review defaults.")
        else:
            if not re.fullmatch(r"\d+(?:,\d+)*", choice):
                raise ValueError("Usage: /select 1,3,5 or all/default")
            numbers = [int(n) for n in choice.split(",")]
            if len(set(numbers)) != len(numbers) or any(
                n < 1 or n > len(picker["entries"]) for n in numbers
            ):
                raise ValueError("Choose unique numbers from the current list.")
            rows = [picker["entries"][n - 1] for n in numbers]
        tags = [row["tag"] for row in rows]
        code = secrets.token_hex(3)
        state["pending"] = {
            "code": code,
            **planned(
                "user-inbounds",
                {
                    "username": picker["username"],
                    "revision": picker["revision"],
                    "selected_tags": tags,
                },
            ),
        }
        return (
            "New selection: "
            + "; ".join(profile_label(row) for row in rows)
            + "\n"
            + profile_summary(rows)
            + f"\nConfirm within five minutes with /confirm {code}"
        )
    if name in {"link", "configs", "config"}:
        if len(words) != (2 if name == "config" else 1):
            raise ValueError(
                f"Usage: /{name} SELECTOR" + (" CONFIG_ID" if name == "config" else "")
            )
        link_args = {"customer": words[0]}
        if name == "config":
            link_args["profile"] = words[1]
        result = dispatch(name, link_args)
        if name == "configs":
            return json.dumps(redact(result), ensure_ascii=False, indent=2)
        value = result["subscription_url"] if name == "link" else result["config_uri"]
        if not isinstance(value, str) or any(c in value for c in "\r\n"):
            raise ValueError("Invalid private link response")
        if len(value) > MAX_MESSAGE:
            raise ValueError("Link exceeds Telegram message size; use the SSH CLI --save-link.")
        return value
    simple = {
        "metrics": "system-metrics",
        "backends": "backends",
        "status": "status",
        "health": "health",
        "doctor": "doctor",
        "monitor": "monitor-status",
        "runmonitor": "monitor-run",
        "alerts": "alerts-status",
        "users": "users",
        "sync": "sync",
        "backup": "backup",
    }
    if name in simple:
        if words:
            raise ValueError("This command takes no arguments")
        result = dispatch(simple[name], {})
    elif name in {
        "alertcontrols",
        "ack",
        "unack",
        "silence",
        "unsilence",
        "rule_enable",
        "rule_disable",
    }:
        positional, options = parse_options(words)
        action = {
            "alertcontrols": "list",
            "rule_enable": "rule-enable",
            "rule_disable": "rule-disable",
        }.get(name, name)
        if name == "alertcontrols":
            if words:
                raise ValueError("Usage: /alertcontrols")
        elif len(positional) != 1 or options.keys() - ({"hours"} if name == "silence" else set()):
            raise ValueError(f"Usage: /{name} TARGET" + (" hours=24" if name == "silence" else ""))
        args: dict[str, Any] = {
            "control_action": action,
            "target": positional[0] if positional else "",
        }
        if name == "silence":
            duration = number(options.get("hours", "24"), "hours")
            if not 0 < duration <= 168:
                raise ValueError("hours must be greater than 0 and at most 168")
            args["hours"] = duration
        if name == "rule_disable":
            args["confirmed"] = True
            code = secrets.token_hex(3)
            state["pending"] = {"code": code, **planned("monitor-control", args)}
            return f"Confirm within five minutes with /confirm {code}"
        result = dispatch("monitor-control", args)
    elif name == "directory":
        if words and re.fullmatch(r"-\d+", words[0]):
            raise ValueError("Page must be positive")
        page = int(words.pop(0)) if words and words[0].isdigit() else 1
        if page < 1:
            raise ValueError("Usage: /directory [PAGE] [SEARCH]")
        result = dispatch(
            "list",
            {
                "limit": 30,
                "offset": (page - 1) * 30,
                "brief": True,
                "search": " ".join(words),
            },
        )
        return (
            "\n".join(f"{row['username']} | {row['name']}" for row in result)
            or "No matching customers."
        )
    elif name in {"customers", "history"}:
        if words and re.fullmatch(r"-\d+", words[0]):
            raise ValueError("Page must be positive")
        if name == "history" and (len(words) > 1 or (words and not words[0].isdigit())):
            raise ValueError(f"Usage: /{name} [PAGE]")
        page = int(words.pop(0)) if words and words[0].isdigit() else 1
        if page < 1:
            raise ValueError(f"Usage: /{name} [PAGE]")
        filters: dict[str, Any] = {
            "limit": 10,
            "offset": (page - 1) * 10,
            "history": name == "history",
        }
        if words:
            filters["search"] = " ".join(words)
        result = dispatch("list", filters)
    elif name in {"show", "check", "enable", "disable"}:
        if len(words) != 1:
            raise ValueError(f"Usage: /{name} SELECTOR")
        result = dispatch(name, {"customer": words[0]})
    elif name == "usage":
        if len(words) != 1:
            raise ValueError("Usage: /usage USER")
        result = dispatch("user-usage", {"username": words[0]})
    elif name in {"create", "attach", "update", "identity", "setinbounds", "rename"}:
        positional, options = parse_options(words)
        if len(positional) != 1:
            raise ValueError(f"Usage: /{name} USER key=value ...")
        username = positional[0]
        if name in {"create", "attach", "update", "setinbounds"} and not re.fullmatch(
            r"[A-Za-z0-9_]{3,32}", username
        ):
            raise ValueError("Username must be 3–32 ASCII letters, digits or underscores")
        if name in {"create", "attach"} and not 1 <= len(options.get("name", username)) <= 200:
            raise ValueError("Name must contain 1–200 characters")
        if (
            name in {"identity", "rename"}
            and "name" in options
            and not 1 <= len(options["name"]) <= 200
        ):
            raise ValueError("Name must contain 1–200 characters")
        if name == "create":
            required = {"quota", "days"}
            if not required <= options.keys():
                raise ValueError("Create requires quota and days; inbounds defaults to default")
            allowed = required | {"name", "telegram", "phone", "protocols", "inbounds"}
            if options.keys() - allowed:
                raise ValueError("Unknown create option")
            protocols = [item for item in options.get("protocols", "").split(",") if item]
            if "protocols" in options and (
                not protocols or not set(protocols) <= {"vless", "vmess", "trojan", "shadowsocks"}
            ):
                raise ValueError("Choose supported protocols: vless, vmess, trojan, shadowsocks")
            if "protocols" in options and "inbounds" in options:
                raise ValueError("Choose inbounds or legacy protocols, not both")
            result = dispatch(
                "user-create",
                {
                    "username": username,
                    "name": options.get("name", username),
                    "telegram": options.get("telegram"),
                    "phone": options.get("phone"),
                    "quota_gb": number(options["quota"], "quota"),
                    "days": days(options["days"]),
                    **(
                        {"protocols": protocols}
                        if "protocols" in options
                        else {"inbounds": options.get("inbounds", "default")}
                    ),
                },
            )
        elif name == "attach":
            if options.keys() - {"name", "telegram", "phone"}:
                raise ValueError("Unknown attach option")
            result = dispatch(
                "create",
                {
                    "username": username,
                    "name": options.get("name", username),
                    "telegram": options.get("telegram"),
                    "phone": options.get("phone"),
                    "profiles": None,
                },
            )
        elif name == "update":
            if not options or options.keys() - {"quota", "days", "status"}:
                raise ValueError("Update accepts quota, days and status")
            if "status" in options and options["status"] not in {"active", "disabled"}:
                raise ValueError("status must be active or disabled")
            result = dispatch(
                "user-update",
                {
                    "username": username,
                    "quota_gb": number(options["quota"], "quota") if "quota" in options else None,
                    "days": days(options["days"]) if "days" in options else None,
                    "status": options.get("status"),
                },
            )
        elif name == "identity":
            if not options or options.keys() - {"name", "telegram", "phone"}:
                raise ValueError("Identity accepts name, telegram and phone")
            result = dispatch(
                "customer-update",
                {
                    "customer": username,
                    "name": options.get("name"),
                    "telegram": options.get("telegram"),
                    "phone": options.get("phone"),
                    "clear_telegram": options.get("telegram") == "",
                    "clear_phone": options.get("phone") == "",
                },
            )
        elif name == "setinbounds":
            if set(options) != {"protocol", "tags"}:
                raise ValueError("Setinbounds requires protocol and tags")
            if options["protocol"] not in {"vless", "vmess", "trojan", "shadowsocks"}:
                raise ValueError("Unsupported protocol")
            result = dispatch(
                "user-inbounds",
                {
                    "username": username,
                    "protocol": options["protocol"],
                    "tags": [item for item in options["tags"].split(",") if item],
                },
            )
        else:
            if set(options) != {"name"} or not options["name"]:
                raise ValueError("Rename requires name")
            result = dispatch("rename", {"customer": username, "name": options["name"]})
    elif name in {"resetusage", "remap", "revoke", "rotate"}:
        positional, options = parse_options(words)
        if len(positional) != 1:
            raise ValueError(f"Usage: /{name} USER")
        if name == "remap":
            if set(options) != {"username"} or not options["username"]:
                raise ValueError("Remap requires username=NEW")
        elif options:
            raise ValueError(f"Usage: /{name} USER")
        operation = {
            "resetusage": "user-reset-usage",
            "remap": "remap",
            "revoke": "revoke",
            "rotate": "rotate-token",
        }[name]
        if name == "resetusage":
            args = {"username": positional[0], "confirmed": True}
        elif name == "remap":
            args = {"customer": positional[0], "username": options["username"]}
        else:
            args = {"customer": positional[0], "confirmed": True}
        code = secrets.token_hex(3)
        state["pending"] = {"code": code, **planned(operation, args)}
        return f"Confirm within five minutes with /confirm {code}"
    elif name == "cancel":
        if words:
            raise ValueError("This command takes no arguments")
        existed = state.pop("pending", None) is not None
        existed = state.pop("picker", None) is not None or existed
        existed = state.pop("receipt_upload", None) is not None or existed
        return "Pending operation cancelled." if existed else "No operation is pending."
    elif name == "confirm":
        pending = state.pop("pending", None)
        if (
            len(words) != 1
            or not isinstance(pending, dict)
            or not secrets.compare_digest(str(pending.get("code", "")), words[0])
            or float(pending.get("expires", 0)) < time.time()
        ):
            raise ValueError("Confirmation is invalid or expired")
        result = dispatch(str(pending["operation"]), dict(pending["args"]))
        if pending["operation"] == "user-inbounds":
            state.pop("picker", None)
    else:
        raise ValueError("Unknown command; use /help")
    output = (
        readable_result(redact(result))
        if name in {"monitor", "runmonitor", "alerts", "alertcontrols", "metrics", "usage", "users"}
        else json.dumps(redact(result), ensure_ascii=False, indent=2)
    )
    return output


def send_reply(token: str, admin_id: int, text: str) -> None:
    # Telegram limits text length; never silently discard the end of a result.
    pages = [text[i : i + MAX_MESSAGE] for i in range(0, len(text), MAX_MESSAGE)] or ["Done."]
    if len(pages) > 8:
        pages = pages[:7] + [
            "Result too large. Use /customers PAGE, /history PAGE "
            "or the SSH CLI for the full inventory."
        ]
    global LAST_SEND
    for page in pages:
        with SEND_LOCK:
            delay = OPTIONS["send_interval_seconds"] - (time.monotonic() - LAST_SEND)
            if delay > 0:
                time.sleep(delay)
            try:
                telegram(
                    token,
                    "sendMessage",
                    {
                        "chat_id": str(admin_id),
                        "text": page,
                        "disable_web_page_preview": "true",
                    },
                )
            finally:
                LAST_SEND = time.monotonic()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    token = os.environ.get("KEYHOLDER_MANAGEMENT_BOT_TOKEN", "")
    administrator = os.environ.get("KEYHOLDER_MANAGEMENT_ADMIN_ID", "")
    if not TOKEN_PATTERN.fullmatch(token) or not re.fullmatch(r"[0-9]{5,20}", administrator):
        raise SystemExit("Invalid management bot configuration")
    admin_id = int(administrator)
    path = Path(
        os.getenv("KEYHOLDER_MANAGEMENT_STATE", "/var/lib/keyholder-management-bot/state.json")
    )
    state = private_state(path)
    state_lock = threading.Lock()
    work: queue.Queue[tuple[Any, float]] = queue.Queue(maxsize=OPTIONS["queue_size"])

    def process() -> None:
        while True:
            text, created_at = work.get()
            started = time.monotonic()
            with state_lock:
                local = {
                    key: state[key]
                    for key in ("pending", "picker", "receipt_upload")
                    if key in state
                }
            try:
                if time.time() - created_at > OPTIONS["command_max_age_seconds"]:
                    raise ValueError("Queued command expired; send it again")
                if isinstance(text, dict):
                    reply = billing_bot.receive(
                        token, text, local, telegram, dispatch, OPTIONS["telegram_api_base"]
                    )
                else:
                    reply = command(text, local)
            except ValueError as error:
                reply = f"Error: {error}"
            except Exception as error:
                logging.warning("Command execution failed: %s", type(error).__name__)
                reply = "Operation failed or timed out. Check state before retrying a change."
            with state_lock:
                for key in ("pending", "picker", "receipt_upload"):
                    state.pop(key, None)
                    if key in local:
                        state[key] = local[key]
                save_state(path, state)
            logging.info("Command completed in %.2fs", time.monotonic() - started)
            try:
                send_reply(token, admin_id, reply)
            except Exception as error:
                logging.warning(
                    "Reply delivery failed: %s; command will not be replayed", type(error).__name__
                )
            finally:
                work.task_done()

    worker = threading.Thread(target=process, name="bot-commands", daemon=True)
    worker.start()
    try:
        telegram(token, "setMyCommands", {"commands": json.dumps(BOT_COMMANDS)})
    except Exception as error:
        logging.warning("Menu registration failed: %s", type(error).__name__)
    failures = 0
    while True:
        if not worker.is_alive():
            raise SystemExit("Command worker stopped; service restart required")
        try:
            payload = telegram(
                token,
                "getUpdates",
                {
                    "offset": str(int(state.get("offset", 0))),
                    "timeout": str(OPTIONS["poll_timeout_seconds"]),
                    "allowed_updates": json.dumps(["message"]),
                    "limit": str(OPTIONS["poll_batch_size"]),
                },
            )
            failures = 0
            for update in payload.get("result", []):
                with state_lock:
                    state["offset"] = int(update["update_id"]) + 1
                    save_state(path, state)
                message = update.get("message") or {}
                if not authorized(message, admin_id):
                    continue
                text = str(message.get("text", ""))
                # Cheap local help and liveness remain responsive during long audits.
                name = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text else ""
                if name in {"/ping", "/help", "/start", "/metrics", "/monitor", "/alerts"}:
                    started = time.monotonic()
                    try:
                        reply = command(text, {})
                    except Exception:
                        reply = "Quick check failed. Use /status or the SSH CLI to investigate."
                    send_reply(token, admin_id, reply)
                    logging.info("Quick command completed in %.2fs", time.monotonic() - started)
                    continue
                if (
                    time.time() - float(message.get("date", time.time()))
                    > OPTIONS["command_max_age_seconds"]
                ):
                    send_reply(
                        token,
                        admin_id,
                        "This queued command has expired. Please send it again.",
                    )
                    continue
                try:
                    work.put_nowait(
                        (
                            message if message.get("photo") or message.get("document") else text,
                            float(message.get("date", time.time())),
                        )
                    )
                except queue.Full:
                    send_reply(
                        token,
                        admin_id,
                        "The command queue is full. Wait for results before retrying.",
                    )
        except Exception as error:
            failures += 1
            if failures == 1 or failures % 10 == 0:
                logging.warning("Telegram polling failed (%d): %s", failures, type(error).__name__)
            time.sleep(
                min(
                    OPTIONS["retry_max_delay_seconds"],
                    2 ** min(failures, OPTIONS["retry_max_exponent"]),
                )
            )


if __name__ == "__main__":
    main()
