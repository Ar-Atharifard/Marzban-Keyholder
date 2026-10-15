#!/usr/bin/env python3
"""Small allowlisted Telegram management client for the host dispatcher."""

from __future__ import annotations

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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_MESSAGE = 3500
CONFIRM_SECONDS = 300
TOKEN_PATTERN = re.compile(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}")
BOT_COMMANDS = [
    {"command": "help", "description": "Show the management command reference"},
    {"command": "metrics", "description": "Show RAM, CPU, swap, storage and uptime"},
    {"command": "status", "description": "Show production container status"},
    {"command": "doctor", "description": "Run the complete Keyholder audit"},
    {"command": "monitor", "description": "Show the latest monitoring result"},
    {"command": "alerts", "description": "Show alert bot and timer status"},
    {"command": "customers", "description": "List active customers"},
    {"command": "users", "description": "List Marzban users"},
    {"command": "cancel", "description": "Cancel a pending destructive operation"},
]


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
    with opener.open(request, timeout=35 if method == "getUpdates" else 10) as response:
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
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def help_text() -> str:
    return """Keyholder management
/ping /metrics /status /health /doctor /monitor /runmonitor /alerts
/users /customers [PAGE] /history [PAGE] /backends /show SELECTOR /check SELECTOR
/usage USER /inbounds
/create USER quota=GB days=N protocols=vless,trojan name="Full Name"
/attach USER name="Full Name"
/update USER quota=GB days=N status=active|disabled
/identity SELECTOR name="Full Name" telegram=@id phone=+number
/setinbounds USER protocol=vless tags=TAG1,TAG2
/rename SELECTOR name="Full Name"
/enable SELECTOR /disable SELECTOR /sync /backup
/resetusage USER /remap SELECTOR username=NEW /revoke SELECTOR /rotate SELECTOR
/confirm CODE /cancel

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
    if name == "ping":
        return "Online."
    if name in {"start", "help"}:
        return help_text()
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
        "inbounds": "inbounds",
        "sync": "sync",
        "backup": "backup",
    }
    if name in simple:
        if words:
            raise ValueError("This command takes no arguments")
        result = dispatch(simple[name], {})
    elif name in {"customers", "history"}:
        if len(words) > 1 or (words and (not words[0].isdigit() or int(words[0]) < 1)):
            raise ValueError(f"Usage: /{name} [PAGE]")
        page = int(words[0]) if words else 1
        result = dispatch(
            "list", {"limit": 10, "offset": (page - 1) * 10, "history": name == "history"}
        )
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
        elif name == "setinbounds":
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
    else:
        raise ValueError("Unknown command; use /help")
    output = json.dumps(redact(result), ensure_ascii=False, indent=2)
    return output


def send_reply(token: str, admin_id: int, text: str) -> None:
    # Telegram limits text length; never silently discard the end of a result.
    pages = [text[i : i + MAX_MESSAGE] for i in range(0, len(text), MAX_MESSAGE)] or ["Done."]
    if len(pages) > 8:
        pages = pages[:7] + [
            "Result too large. Use /customers PAGE, /history PAGE "
            "or the SSH CLI for the full inventory."
        ]
    for page in pages:
        telegram(
            token,
            "sendMessage",
            {
                "chat_id": str(admin_id),
                "text": page,
                "disable_web_page_preview": "true",
            },
        )


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
    work: queue.Queue[str] = queue.Queue(maxsize=4)

    def process() -> None:
        while True:
            text = work.get()
            started = time.monotonic()
            with state_lock:
                local = {"pending": state["pending"]} if "pending" in state else {}
            try:
                reply = command(text, local)
            except ValueError as error:
                reply = f"Error: {error}"
            except Exception as error:
                logging.warning("Command execution failed: %s", type(error).__name__)
                reply = "Operation failed or timed out. Check state before retrying a change."
            with state_lock:
                state.pop("pending", None)
                if "pending" in local:
                    state["pending"] = local["pending"]
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

    threading.Thread(target=process, name="bot-commands", daemon=True).start()
    try:
        telegram(token, "setMyCommands", {"commands": json.dumps(BOT_COMMANDS)})
    except Exception as error:
        logging.warning("Menu registration failed: %s", type(error).__name__)
    failures = 0
    while True:
        try:
            payload = telegram(
                token,
                "getUpdates",
                {
                    "offset": str(int(state.get("offset", 0))),
                    "timeout": "25",
                    "allowed_updates": json.dumps(["message"]),
                    "limit": "10",
                },
            )
            failures = 0
            for update in payload.get("result", []):
                with state_lock:
                    state["offset"] = int(update["update_id"]) + 1
                    save_state(path, state)
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                sender = message.get("from") or {}
                if (
                    chat.get("type") != "private"
                    or chat.get("id") != admin_id
                    or sender.get("id") != admin_id
                ):
                    continue
                text = str(message.get("text", ""))[:2048]
                # Cheap local help and liveness remain responsive during long audits.
                name = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text else ""
                if name in {"/ping", "/help", "/start"}:
                    send_reply(token, admin_id, "Online." if name == "/ping" else help_text())
                    continue
                if time.time() - float(message.get("date", time.time())) > 300:
                    send_reply(
                        token,
                        admin_id,
                        "This queued command is over five minutes old. Please send it again.",
                    )
                    continue
                try:
                    work.put_nowait(text)
                except queue.Full:
                    send_reply(
                        token,
                        admin_id,
                        "Four commands are already queued. Wait for their results before retrying.",
                    )
        except Exception as error:
            failures += 1
            if failures == 1 or failures % 10 == 0:
                logging.warning("Telegram polling failed (%d): %s", failures, type(error).__name__)
            time.sleep(min(30, 2 ** min(failures, 5)))


if __name__ == "__main__":
    main()
