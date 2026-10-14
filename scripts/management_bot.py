#!/usr/bin/env python3
"""Small allowlisted Telegram management client for the host dispatcher."""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_MESSAGE = 3500
CONFIRM_SECONDS = 300
TOKEN_PATTERN = re.compile(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}")


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
        f"https://api.telegram.org/bot{token}/{method}", data=data, method="POST"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=40) as response:
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
        timeout=70,
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
            if key not in {"token", "subscription_url", "panel_url", "password"}
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
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result


def help_text() -> str:
    return """Keyholder management
/status /health /doctor /monitor
/users /customers /show SELECTOR /usage USER /inbounds
/create USER quota=GB days=N protocols=vless,trojan name="Full Name"
/attach USER name="Full Name"
/update USER quota=GB days=N status=active|disabled
/identity SELECTOR name="Full Name" telegram=@id phone=+number
/setinbounds USER protocol=vless tags=TAG1,TAG2
/enable SELECTOR /disable SELECTOR /sync /backup
/resetusage USER /revoke SELECTOR /rotate SELECTOR then /confirm CODE

Subscription links are intentionally available only through the SSH CLI."""


def planned(command: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"operation": command, "args": args, "expires": time.time() + CONFIRM_SECONDS}


def command(text: str, state: dict[str, Any]) -> str:
    try:
        words = shlex.split(text, posix=True)
    except ValueError:
        raise ValueError("Invalid quoting") from None
    if not words or not words[0].startswith("/"):
        return help_text()
    name = words.pop(0).split("@", 1)[0].removeprefix("/").lower()
    if name in {"start", "help"}:
        return help_text()
    simple = {
        "status": "status",
        "health": "health",
        "doctor": "doctor",
        "monitor": "monitor-status",
        "users": "users",
        "inbounds": "inbounds",
        "sync": "sync",
        "backup": "backup",
    }
    if name in simple:
        if words:
            raise ValueError("This command takes no arguments")
        result = dispatch(simple[name], {})
    elif name == "customers":
        if words:
            raise ValueError("This command takes no arguments")
        result = dispatch("list", {"limit": 100, "offset": 0, "history": False})
    elif name in {"show", "enable", "disable"}:
        if len(words) != 1:
            raise ValueError(f"Usage: /{name} SELECTOR")
        result = dispatch(name, {"customer": words[0]})
    elif name == "usage":
        if len(words) != 1:
            raise ValueError("Usage: /usage USER")
        result = dispatch("user-usage", {"username": words[0]})
    elif name in {"create", "attach", "update", "identity", "setinbounds"}:
        positional, options = parse_options(words)
        if len(positional) != 1:
            raise ValueError(f"Usage: /{name} USER key=value ...")
        username = positional[0]
        if name == "create":
            required = {"quota", "days", "protocols"}
            if not required <= options.keys():
                raise ValueError("Create requires quota, days and protocols")
            allowed = required | {"name", "telegram", "phone"}
            if options.keys() - allowed:
                raise ValueError("Unknown create option")
            protocols = [item for item in options["protocols"].split(",") if item]
            if not protocols:
                raise ValueError("At least one protocol is required")
            result = dispatch(
                "user-create",
                {
                    "username": username,
                    "name": options.get("name", username),
                    "telegram": options.get("telegram"),
                    "phone": options.get("phone"),
                    "quota_gb": number(options["quota"], "quota"),
                    "days": int(number(options["days"], "days")),
                    "protocols": protocols,
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
            result = dispatch(
                "user-update",
                {
                    "username": username,
                    "quota_gb": number(options["quota"], "quota") if "quota" in options else None,
                    "days": int(number(options["days"], "days")) if "days" in options else None,
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
        else:
            if set(options) != {"protocol", "tags"}:
                raise ValueError("Setinbounds requires protocol and tags")
            result = dispatch(
                "user-inbounds",
                {
                    "username": username,
                    "protocol": options["protocol"],
                    "tags": [item for item in options["tags"].split(",") if item],
                },
            )
    elif name in {"resetusage", "revoke", "rotate"}:
        if len(words) != 1:
            raise ValueError(f"Usage: /{name} USER")
        operation = {
            "resetusage": "user-reset-usage",
            "revoke": "revoke",
            "rotate": "rotate-token",
        }[name]
        args = (
            {"username": words[0], "confirmed": True}
            if name == "resetusage"
            else {"customer": words[0], "confirmed": True}
        )
        code = secrets.token_hex(3)
        state["pending"] = {"code": code, **planned(operation, args)}
        return f"Confirm within five minutes with /confirm {code}"
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
    else:
        raise ValueError("Unknown command; use /help")
    output = json.dumps(redact(result), ensure_ascii=False, indent=2)
    return output[:MAX_MESSAGE]


def main() -> None:
    token = os.environ.get("KEYHOLDER_MANAGEMENT_BOT_TOKEN", "")
    administrator = os.environ.get("KEYHOLDER_MANAGEMENT_ADMIN_ID", "")
    if not TOKEN_PATTERN.fullmatch(token) or not re.fullmatch(r"[0-9]{5,20}", administrator):
        raise SystemExit("Invalid management bot configuration")
    admin_id = int(administrator)
    path = Path(
        os.getenv("KEYHOLDER_MANAGEMENT_STATE", "/var/lib/keyholder-management-bot/state.json")
    )
    state = private_state(path)
    while True:
        try:
            payload = telegram(
                token,
                "getUpdates",
                {
                    "offset": str(int(state.get("offset", 0))),
                    "timeout": "30",
                    "allowed_updates": json.dumps(["message"]),
                },
            )
            for update in payload.get("result", []):
                state["offset"] = int(update["update_id"]) + 1
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                sender = message.get("from") or {}
                if (
                    chat.get("type") != "private"
                    or chat.get("id") != admin_id
                    or sender.get("id") != admin_id
                ):
                    continue
                try:
                    reply = command(str(message.get("text", ""))[:2048], state)
                except Exception as error:
                    reply = f"Error: {error}"
                telegram(
                    token,
                    "sendMessage",
                    {
                        "chat_id": str(admin_id),
                        "text": reply[:MAX_MESSAGE],
                        "disable_web_page_preview": "true",
                    },
                )
                save_state(path, state)
            save_state(path, state)
        except Exception:
            time.sleep(5)


if __name__ == "__main__":
    main()
