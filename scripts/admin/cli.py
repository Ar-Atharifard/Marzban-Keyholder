#!/usr/bin/env python3
"""Manage Keyholder through SSH without exporting administrator credentials."""

import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

KINDS = ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]
REMOTE = "python3 /usr/local/lib/keyholder-admin/host.py"


class CLIError(Exception):
    pass


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="braavos", help="SSH alias for administration")
    p.add_argument("--local", action="store_true", help="Run on the VPS as root")
    p.add_argument("--json", action="store_true", help="JSON output for nonsecret results")
    commands = p.add_subparsers(dest="operation", required=True)
    for op in ["status", "health", "backup"]:
        commands.add_parser(op)
    panel = commands.add_parser("panel", help="Open the private Marzban panel through SSH")
    panel.add_argument("--port", type=int, default=28080)
    panel.add_argument("--no-browser", action="store_true")
    bookmark = commands.add_parser("panel-url", help="Show the private public-panel bookmark")
    bookmark.add_argument("--save-link", type=Path)
    listing = commands.add_parser("list", help="List customers without subscription tokens")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    create = commands.add_parser("create", help="Attach an existing active Marzban user")
    create.add_argument("username")
    create.add_argument("--name", help="Display name; defaults to Marzban username")
    create.add_argument("--profiles", nargs="+", choices=KINDS)
    create.add_argument(
        "--save-link", type=Path, help="Explicit private local file, never overwritten"
    )
    for op in [
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
        if op == "rotate-token":
            command.add_argument("--save-link", type=Path)
    return p


def request(host: str, payload: dict[str, Any], local: bool = False) -> dict[str, Any]:
    command = (
        ["python3", "/usr/local/lib/keyholder-admin/host.py"]
        if local
        else [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ConnectTimeout=10",
            host,
            REMOTE,
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
                "\t".join(safe(item[k]) for k in ["id", "name", "status"]),
                safe(item["mapping"]["upstream_username"]),
                sep="\t",
            )
        else:
            print(json.dumps(item, ensure_ascii=False))


def run_panel(args: argparse.Namespace) -> int:
    if not 1024 <= args.port <= 65535:
        raise CLIError("Choose a local port between 1024 and 65535.")
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-N",
        "-L",
        f"127.0.0.1:{args.port}:127.0.0.1:8000",
        args.host,
    ]
    process = subprocess.Popen(command)
    url = f"http://127.0.0.1:{args.port}/dashboard/"
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
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.host):
        p.error("Use an SSH alias without options, credentials or shell expressions.")
    if args.operation == "list" and (not 1 <= args.limit <= 100 or args.offset < 0):
        p.error("Limit must be 1–100 and offset must be nonnegative.")
    if args.operation in {"create", "remap"} and not re.fullmatch(
        r"[A-Za-z0-9_]{3,32}", args.username
    ):
        p.error("Marzban usernames must be 3–32 ASCII letters, digits or underscores.")
    if args.operation in {"revoke", "rotate-token"} and not args.confirmed:
        p.error("Use --confirm: revocation is permanent; rotation invalidates the old link.")
    if args.operation == "create":
        args.name = args.name or args.username
    if args.operation in {"create", "rename"} and not 1 <= len(args.name) <= 200:
        p.error("Name must contain 1–200 characters.")
    if args.local and (os.geteuid() != 0 or args.operation == "panel"):
        p.error("--local is for root on the VPS; panel forwarding runs on the workstation.")
    secret = args.operation in {"create", "rotate-token", "panel-url"}
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
                if k not in {"operation", "host", "json", "save_link", "local"}
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
            if fd is not None:
                with os.fdopen(fd, "w") as file:
                    fd = None
                    file.write(json.dumps(credentials, indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                print("Private link file saved. Keep it in secure storage.")
            elif args.operation == "panel-url":
                print("Private panel bookmark:", result["panel_url"])
                if not result["active"]:
                    print("Prepared only: public access awaits Cloudflare configuration.")
            else:
                print("Customer ID:", result["customer"]["id"])
                print("Subscription URL:", result["subscription_url"])
                print("Save this privately; existing links cannot be recovered from their hashes.")
        else:
            display(result, args.json)
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
