#!/usr/bin/env python3
"""Manage Keyholder through SSH without exporting administrator credentials."""

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from keyholder.profile_types import DEFAULT_PROFILES, SUPPORTED_KINDS

DEFAULT_KINDS = list(DEFAULT_PROFILES)
KINDS = list(SUPPORTED_KINDS)


def operator_config() -> dict[str, str]:
    configured = os.getenv("KEYHOLDER_ADMIN_CONFIG")
    path = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / ".private/admin.json"
    )
    if not path.exists():
        if configured:
            raise ValueError("Operator configuration file missing")
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ValueError("Invalid operator configuration")
    return {str(k): str(v) for k, v in data.items()}


def remote_path() -> str:
    path = operator_config().get("remote_path", "/usr/local/lib/keyholder-admin/host.py")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in Path(path).parts:
        raise ValueError("Invalid remote dispatcher path")
    return path


def ssh_command() -> list[str]:
    command = ["ssh"]
    configured = operator_config().get("ssh_config")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Invalid SSH configuration path")
        command.extend(["-F", str(path)])
    return command


class CLIError(Exception):
    pass


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--host",
        default=operator_config().get("host", "keyholder-server"),
        help="SSH alias for administration",
    )
    p.add_argument("--local", action="store_true", help="Run on the VPS as root")
    p.add_argument("--json", action="store_true", help="JSON output for nonsecret results")
    p.add_argument(
        "--backend",
        dest="backend_id",
        default=os.getenv("KEYHOLDER_OPERATOR_BACKEND_ID", "marzban-default"),
    )
    commands = p.add_subparsers(dest="operation", required=True)
    initialize = commands.add_parser("init-config", help="Create a private environment template")
    initialize.add_argument("--output", type=Path, default=Path(".env"))
    for op in [
        "status",
        "health",
        "doctor",
        "backup",
        "backends",
        "backend-register",
        "monitor-status",
        "monitor-run",
    ]:
        commands.add_parser(op)
    for op in ["users", "inbounds", "sync"]:
        commands.add_parser(op)
    reconcile = commands.add_parser(
        "reconcile", help="Rotate legacy canonical links and revoke duplicates"
    )
    reconcile.add_argument("--confirm", action="store_true", dest="confirmed")
    user_create = commands.add_parser(
        "user-create", help="Provision Marzban and register a stable link"
    )
    user_create.add_argument("username")
    user_create.add_argument("--name", help="Private customer name; defaults to username")
    user_create.add_argument("--telegram", help="Unique Telegram username or numeric ID")
    user_create.add_argument(
        "--phone", help="Unique international phone number, for example +98912..."
    )
    user_create.add_argument(
        "--quota-gb", type=float, required=True, help="0 explicitly means unlimited"
    )
    user_create.add_argument("--days", type=int, required=True, help="0 explicitly means no expiry")
    user_create.add_argument(
        "--protocols", nargs="+", choices=["vless", "vmess", "trojan", "shadowsocks"], required=True
    )
    user_create.add_argument("--save-link", type=Path)
    user_update = commands.add_parser("user-update", help="Modify quota, expiry or panel status")
    user_update.add_argument("username")
    user_update.add_argument("--quota-gb", type=float)
    user_update.add_argument("--days", type=int)
    user_update.add_argument("--status", choices=["active", "disabled"])
    inbound = commands.add_parser("user-inbounds", help="Select panel inbounds for one protocol")
    inbound.add_argument("username")
    inbound.add_argument(
        "--protocol", choices=["vless", "vmess", "trojan", "shadowsocks"], required=True
    )
    inbound.add_argument(
        "--tags", nargs="*", required=True, help="Empty selection disables this protocol's inbounds"
    )
    usage = commands.add_parser("user-usage", help="Read panel traffic usage for a user")
    usage.add_argument("username")
    reset = commands.add_parser("user-reset-usage", help="Reset a user's used traffic explicitly")
    reset.add_argument("username")
    reset.add_argument("--confirm", action="store_true", dest="confirmed")
    panel = commands.add_parser("panel", help="Open the private Marzban panel through SSH")
    panel.add_argument("--port", type=int, default=28080)
    panel.add_argument("--no-browser", action="store_true")
    bookmark = commands.add_parser("panel-url", help="Show the panel URL")
    bookmark.add_argument("--save-link", type=Path)
    listing = commands.add_parser("list", help="List customers without subscription tokens")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--history", action="store_true")
    create = commands.add_parser("create", help="Attach an existing active Marzban user")
    create.add_argument("username")
    create.add_argument("--name", help="Display name; defaults to Marzban username")
    create.add_argument("--telegram", help="Unique Telegram username or numeric ID")
    create.add_argument("--phone", help="Unique international phone number, for example +98912...")
    create.add_argument("--profiles", nargs="+", choices=KINDS)
    create.add_argument(
        "--save-link", type=Path, help="Explicit private local file, never overwritten"
    )
    customer_update = commands.add_parser(
        "customer-update", help="Update private customer identity metadata"
    )
    customer_update.add_argument("customer", help="Customer ID, username, Telegram or phone")
    customer_update.add_argument("--name")
    customer_update.add_argument("--telegram")
    customer_update.add_argument("--phone")
    customer_update.add_argument("--clear-telegram", action="store_true")
    customer_update.add_argument("--clear-phone", action="store_true")
    for op in [
        "link",
        "show",
        "check",
        "enable",
        "disable",
        "revoke",
        "rotate-token",
        "rename",
        "remap",
        "profiles",
    ]:
        command = commands.add_parser(op)
        command.add_argument("customer", help="Customer ID or unambiguous Marzban username")
        if op == "rename":
            command.add_argument("name")
        if op == "remap":
            command.add_argument("username")
        if op == "profiles":
            command.add_argument("profiles", nargs="+", choices=KINDS)
        if op in {"revoke", "rotate-token"}:
            command.add_argument("--confirm", action="store_true", dest="confirmed")
        if op == "link":
            command.add_argument("--info", action="store_true", help="Show the usage-page URL")
        if op in {"rotate-token", "link"}:
            command.add_argument("--save-link", type=Path)
    return p


def request(host: str, payload: dict[str, Any], local: bool = False) -> dict[str, Any]:
    command = (
        ["python3", remote_path()]
        if local
        else [
            *ssh_command(),
            "-o",
            "BatchMode=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ConnectTimeout=10",
            host,
            "python3 " + remote_path(),
        ]
    )
    process = subprocess.run(
        command, input=json.dumps(payload).encode(), capture_output=True, timeout=75
    )
    try:
        envelope = json.loads(process.stdout)
    except ValueError:
        raise CLIError("SSH request failed; for mutations, check state before retrying.") from None
    if not envelope.get("ok"):
        raise CLIError(envelope.get("error", "Server operation failed."))
    return envelope  # type: ignore[no-any-return]


def safe(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def display(result: Any, as_json: bool) -> None:
    if as_json or not isinstance(result, list):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    for item in result:
        if "mapping" in item:
            print(
                safe(item["mapping"]["upstream_username"]),
                "\t".join(
                    safe(item.get(k, "")) for k in ["id", "telegram", "phone", "status", "name"]
                ),
                sep="\t",
            )
        else:
            print(json.dumps(item, ensure_ascii=False))


def run_panel(args: argparse.Namespace) -> int:
    if not 1024 <= args.port <= 65535:
        raise CLIError("Choose a local port between 1024 and 65535.")
    command = [
        *ssh_command(),
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-N",
        "-L",
        f"127.0.0.1:{args.port}:{operator_config().get('panel_target', '127.0.0.1:8000')}",
        args.host,
    ]
    process = subprocess.Popen(command)
    url = f"http://127.0.0.1:{args.port}" + operator_config().get("panel_path", "/dashboard/")
    try:
        import time

        time.sleep(1)
        if process.poll() is not None:
            raise CLIError("Panel tunnel failed; check SSH access or choose another local port.")
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        print("Keep this terminal open. Press Ctrl+C to close the tunnel.", flush=True)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.operation == "init-config":
        contents = (
            "KEYHOLDER_ADMIN_KEY=" + secrets.token_urlsafe(48) + "\n"
            "KEYHOLDER_TOKEN_ENCRYPTION_KEY="
            + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            + "\n"
            "KEYHOLDER_DATABASE_URL=sqlite:///./data/keyholder.db\n"
            "KEYHOLDER_PUBLIC_BASE_URL=https://subscription.example.invalid\n"
            "KEYHOLDER_MARZBAN_URL=http://127.0.0.1:8000\n"
            "KEYHOLDER_PROFILE_SOURCE=upstream\n"
        )
        try:
            init_fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(init_fd, "w") as file:
                file.write(contents)
            print("Private environment created. Set your public URL and upstream credentials.")
            return 0
        except OSError:
            print(
                "Configuration creation failed; existing files are never overwritten.",
                file=sys.stderr,
            )
            return 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.host):
        p.error("Use an SSH alias without options, credentials or shell expressions.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.backend_id):
        p.error("Invalid backend ID.")
    if args.operation == "list" and (not 1 <= args.limit <= 100 or args.offset < 0):
        p.error("Limit must be 1–100 and offset must be nonnegative.")
    if args.operation in {
        "create",
        "remap",
        "user-create",
        "user-update",
        "user-inbounds",
        "user-usage",
        "user-reset-usage",
    } and not re.fullmatch(r"[A-Za-z0-9_]{3,32}", args.username):
        p.error("Marzban usernames must be 3–32 ASCII letters, digits or underscores.")
    if (
        args.operation in {"revoke", "rotate-token", "reconcile", "user-reset-usage"}
        and not args.confirmed
    ):
        p.error(
            "Use --confirm: revocation, token rotation and traffic reset are explicit operations."
        )
    if args.operation in {"create", "user-create"}:
        args.name = args.name or args.username
    if args.operation in {"create", "user-create", "rename"} and not 1 <= len(args.name) <= 200:
        p.error("Name must contain 1–200 characters.")
    if args.operation == "customer-update":
        if args.clear_telegram and args.telegram is not None:
            p.error("Use either --telegram or --clear-telegram.")
        if args.clear_phone and args.phone is not None:
            p.error("Use either --phone or --clear-phone.")
        if args.name is not None and not 1 <= len(args.name) <= 200:
            p.error("Name must contain 1–200 characters.")
        if not any(
            [
                args.name is not None,
                args.telegram is not None,
                args.phone is not None,
                args.clear_telegram,
                args.clear_phone,
            ]
        ):
            p.error("Specify at least one customer identity change.")
    if args.local and (os.geteuid() != 0 or args.operation == "panel"):
        p.error("--local is for root on the VPS; panel forwarding runs on the workstation.")
    if args.operation in {"user-create", "user-update"}:
        import math

        if args.quota_gb is not None and (not math.isfinite(args.quota_gb) or args.quota_gb < 0):
            p.error("Quota must be finite and nonnegative.")
        if args.days is not None and not 0 <= args.days <= 36500:
            p.error("Days must be 0–36500.")
        if args.operation == "user-update" and all(
            getattr(args, k) is None for k in ["quota_gb", "days", "status"]
        ):
            p.error("Specify at least one change.")
    secret = args.operation in {"create", "user-create", "link", "rotate-token", "panel-url"}
    destination = getattr(args, "save_link", None)
    if secret and not destination and (not sys.stdout.isatty() or args.json):
        p.error("Links require an interactive terminal or explicit --save-link private file.")
    fd = None
    try:
        if args.operation == "panel":
            return run_panel(args)
        if destination:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        payload = {
            "operation": args.operation,
            "args": {
                k: v
                for k, v in vars(args).items()
                if k not in {"operation", "host", "json", "save_link", "local", "info"}
            },
        }
        result = (
            request(args.host, payload, local=True) if args.local else request(args.host, payload)
        )["result"]
        if secret:
            credentials = (
                {"panel_url": result["panel_url"], "active": result["active"]}
                if args.operation == "panel-url"
                else {
                    "customer_id": result["customer"]["id"],
                    "subscription_url": result["subscription_url"],
                }
            )
            if getattr(args, "info", False):
                credentials["usage_url"] = result["subscription_url"] + "?format=info"
            if fd is not None:
                with os.fdopen(fd, "w") as file:
                    fd = None
                    file.write(json.dumps(credentials, indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                print("Private link file saved. Keep it in secure storage.")
            elif args.operation == "panel-url":
                print("Panel URL:", result["panel_url"])
                if not result["active"]:
                    print("Prepared only: public access is not active yet.")
            else:
                print("Customer ID:", result["customer"]["id"])
                if getattr(args, "info", False):
                    print("Usage URL:", credentials["usage_url"])
                else:
                    print("Subscription URL:", result["subscription_url"])
                print(
                    "Retrieve this same link later with keyholder link USER; rotation is explicit."
                )
        else:
            display(result, args.json)
        if args.operation in {"doctor", "monitor-run", "monitor-status"} and not result.get(
            "healthy", False
        ):
            return 1
        return 0
    except CLIError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        # A create/rotation may have succeeded even if its response was lost.
        print(
            "Operation failed. Check SSH, customer state and output permissions before retrying.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if fd is not None:
            os.close(fd)
            assert destination is not None
            destination.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
