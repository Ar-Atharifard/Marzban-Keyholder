#!/usr/bin/env python3
"""Manage Keyholder through SSH without exporting administrator credentials."""

from __future__ import annotations

import argparse
import base64
import getpass
import importlib.metadata
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


class KeyholderParser(argparse.ArgumentParser):
    command_parsers: dict[tuple[str, ...], KeyholderParser]


COMMAND_HELP = {
    "tls-configure": "Configure automatic public HTTPS certificates with a private DNS token.",
    "tls-status": "Show public certificate readiness and renewal service state.",
    "tls-issue": "Start certificate issuance or retry automatic renewal.",
    "init-config": "Create a new mode-0600 environment template without overwriting files.",
    "status": "Show container state and the deployed API revision.",
    "health": "Check Keyholder's authenticated application health endpoint.",
    "doctor": "Audit database revision, token vault, mappings, links and upstream inventory.",
    "backup": "Create a root-only recovery snapshot of Keyholder, Marzban and configuration.",
    "backends": "List registered subscription backends without exposing credentials.",
    "backend-register": "Register the configured backend in Keyholder's backend registry.",
    "monitor-status": "Read the most recent host-monitor result without running checks.",
    "system-metrics": "Read live memory, CPU, disk, uptime and network metrics.",
    "monitor-control": "Manage notification acknowledgement, silences and disabled rules.",
    "monitor-run": "Run host, service and customer checks now without sending notifications.",
    "alerts-configure": "Configure the Telegram alert bot interactively and privately.",
    "alerts-status": "Show alert delivery, timer and heartbeat configuration status.",
    "alerts-test": "Send a test message through the configured Telegram alert bot.",
    "heartbeat-configure": "Configure an external Better Stack heartbeat interactively.",
    "heartbeat-test": "Send a test ping to the configured external heartbeat.",
    "management-bot-configure": "Configure and enable the allowlisted Telegram management bot.",
    "management-bot-status": "Show whether the management bot is configured and running.",
    "management-bot-test": "Send a test message through the management bot.",
    "users": "List upstream Marzban users without credentials.",
    "inbounds": "List available upstream inbound tags by protocol.",
    "sync": "Register active upstream users that do not yet have a Keyholder customer.",
    "reconcile": "Rotate legacy canonical links and revoke duplicate registrations.",
    "user-create": "Provision a Marzban user and create one stable Keyholder subscription.",
    "user-update": "Change an upstream user's quota, expiry or enabled state.",
    "user-inbounds": "Show a numbered inbound picker or replace an explicit protocol selection.",
    "user-defaults": "View or change the inbound selection for future users.",
    "user-usage": "Read an upstream user's current traffic and plan state.",
    "user-reset-usage": "Reset an upstream user's traffic counter after confirmation.",
    "personal-dnstt": "Export the owner-only DNSTT desktop profile privately.",
    "personal-masque": "Run a local administrator-only MASQUE/HTTP2 recovery proxy.",
    "panel": "Open the private Marzban panel through a local SSH tunnel.",
    "panel-url": "Show or privately save the legacy prepared panel bookmark.",
    "list": "List canonical Keyholder customers without subscription tokens.",
    "create": "Attach an existing active upstream user to one stable subscription.",
    "customer-update": "Update private identity metadata stored only by Keyholder.",
    "link": "Retrieve a customer's existing stable URL without creating a new one.",
    "configs": "List a customer's current connection configurations without credentials.",
    "config": "Retrieve one current configuration URI by its listed ID or unique family.",
    "show": "Show one canonical customer and its upstream mapping.",
    "check": "Check one customer's upstream profiles and rendered subscription.",
    "enable": "Resume Keyholder subscription delivery for a customer.",
    "disable": "Pause Keyholder subscription delivery for a customer.",
    "revoke": "Permanently revoke a customer registration after confirmation.",
    "rotate-token": "Replace a subscription token and invalidate the old URL.",
    "rename": "Change the private Keyholder display name without changing Marzban.",
    "remap": "Map a customer to a different upstream username without rotating its URL.",
    "profiles": "Set the rendered profile kinds for a customer override.",
}

GROUP_HELP = {
    "tls": "Manage public HTTPS certificate issuance and renewal.",
    "config": "Initialize local configuration files.",
    "system": "Inspect and protect the Keyholder deployment.",
    "backend": "Manage subscription backend registrations.",
    "monitor": "Inspect or run local monitoring checks.",
    "alert-bot": "Configure Telegram operational alerts.",
    "heartbeat": "Configure external whole-host outage detection.",
    "management-bot": "Configure the private Telegram management interface.",
    "upstream": "Inspect and synchronize upstream panel resources.",
    "user": "Provision and manage upstream user accounts.",
    "customer": "Manage stable Keyholder customer registrations.",
    "panel": "Access the private upstream administration panel.",
    "personal": "Access owner-only tools outside customer subscriptions.",
}

LEGACY_COMMANDS = {
    "init-config": ("config", "init"),
    "status": ("system", "status"),
    "health": ("system", "health"),
    "doctor": ("system", "doctor"),
    "backup": ("system", "backup"),
    "backends": ("backend", "list"),
    "backend-register": ("backend", "register"),
    "monitor-status": ("monitor", "status"),
    "monitor-run": ("monitor", "run"),
    "alerts-configure": ("alert-bot", "configure"),
    "alerts-status": ("alert-bot", "status"),
    "alerts-test": ("alert-bot", "test"),
    "heartbeat-configure": ("heartbeat", "configure"),
    "heartbeat-test": ("heartbeat", "test"),
    "management-bot-configure": ("management-bot", "configure"),
    "management-bot-status": ("management-bot", "status"),
    "management-bot-test": ("management-bot", "test"),
    "users": ("upstream", "users"),
    "inbounds": ("upstream", "inbounds"),
    "sync": ("upstream", "sync"),
    "reconcile": ("upstream", "reconcile"),
    "user-create": ("user", "create"),
    "create": ("user", "attach"),
    "user-update": ("user", "update"),
    "user-inbounds": ("user", "inbounds"),
    "user-usage": ("user", "usage"),
    "user-reset-usage": ("user", "reset-usage"),
    "list": ("customer", "list"),
    "customer-update": ("customer", "update"),
    "link": ("customer", "link"),
    "show": ("customer", "show"),
    "check": ("customer", "check"),
    "enable": ("customer", "enable"),
    "disable": ("customer", "disable"),
    "revoke": ("customer", "revoke"),
    "rotate-token": ("customer", "rotate-token"),
    "rename": ("customer", "rename"),
    "remap": ("customer", "remap"),
    "profiles": ("customer", "profiles"),
    "panel": ("panel", "open"),
    "panel-url": ("panel", "url"),
}


def normalize_argv(argv: list[str]) -> list[str]:
    """Translate the previous flat CLI into the stable resource/action grammar."""
    normalized = list(argv)
    index = 0
    while index < len(normalized):
        value = normalized[index]
        if value in {"--host", "--backend"}:
            index += 2
            continue
        if value in {"--local", "--json", "--version", "-h", "--help"} or value.startswith(
            ("--host=", "--backend=")
        ):
            index += 1
            continue
        break
    if index >= len(normalized):
        return normalized
    if normalized[index] == "help" and index + 1 < len(normalized):
        replacement = LEGACY_COMMANDS.get(normalized[index + 1])
        if replacement:
            normalized[index + 1 : index + 2] = replacement
        return normalized
    replacement = LEGACY_COMMANDS.get(normalized[index])
    if replacement:
        normalized[index : index + 1] = replacement
    return normalized


def package_version() -> str:
    try:
        return importlib.metadata.version("keyholder")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def parser() -> KeyholderParser:
    p = KeyholderParser(
        description=__doc__,
        epilog=(
            "Use 'keyholder help RESOURCE ACTION' or "
            "'keyholder RESOURCE ACTION --help' for details.\n"
            "Examples:\n"
            "  keyholder system doctor\n"
            "  keyholder user create customer_001 --quota-gb 20 --days 30 --inbounds default\n"
            "  keyholder customer link customer_001 --save-link ./customer_001.json\n"
            "  keyholder panel open"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
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
        help="Backend namespace (default: %(default)s)",
    )
    resources = p.add_subparsers(dest="resource", required=True, metavar="RESOURCE")
    command_parsers: dict[tuple[str, ...], KeyholderParser] = {}

    def group(name: str) -> tuple[KeyholderParser, argparse._SubParsersAction[KeyholderParser]]:
        item = resources.add_parser(name, help=GROUP_HELP[name], description=GROUP_HELP[name])
        command_parsers[(name,)] = item
        actions = item.add_subparsers(dest="action", required=True, metavar="ACTION")
        return item, actions

    def leaf(
        resource: str,
        actions: argparse._SubParsersAction[KeyholderParser],
        action: str,
        operation: str,
        description: str | None = None,
    ) -> KeyholderParser:
        text = description or COMMAND_HELP[operation]
        item = actions.add_parser(action, help=text, description=text)
        item.set_defaults(operation=operation)
        command_parsers[(resource, action)] = item
        return item

    _, config = group("config")
    initialize = leaf("config", config, "init", "init-config")
    initialize.add_argument("--output", type=Path, default=Path(".env"), help="New file path")

    _, system = group("system")
    for action in ["status", "health", "doctor", "backup"]:
        leaf("system", system, action, action)

    leaf("system", system, "metrics", "system-metrics")

    _, tls = group("tls")
    tls_configure = leaf("tls", tls, "configure", "tls-configure")
    tls_configure.add_argument("domain", help="Existing public subscription hostname")
    tls_configure.add_argument("--email", required=True, help="Certificate renewal contact email")
    leaf("tls", tls, "status", "tls-status")
    leaf("tls", tls, "issue", "tls-issue")

    _, backend = group("backend")
    leaf("backend", backend, "list", "backends")
    leaf("backend", backend, "register", "backend-register")

    _, monitor = group("monitor")
    leaf("monitor", monitor, "status", "monitor-status")
    leaf("monitor", monitor, "run", "monitor-run")
    for action, description in {
        "controls": "List alert rules, incidents and notification controls.",
        "ack": "Acknowledge the current occurrence and stop its reminders.",
        "unack": "Remove acknowledgement of one alert key.",
        "silence": "Temporarily mute one alert key for at most 168 hours.",
        "unsilence": "Remove temporary silence from one alert key.",
        "rule-disable": "Disable a notification rule with explicit confirmation.",
        "rule-enable": "Enable notifications for one rule again.",
    }.items():
        item = leaf("monitor", monitor, action, "monitor-control", description)
        item.set_defaults(control_action="list" if action == "controls" else action)
        if action != "controls":
            item.add_argument("target", help="Exact alert key, or rule ID for rule actions")
        if action == "silence":
            item.add_argument(
                "--hours",
                type=float,
                default=24,
                help="Duration, greater than 0 and at most 168 hours",
            )
        if action == "rule-disable":
            item.add_argument("--confirm", action="store_true", dest="confirmed")

    _, alert_bot = group("alert-bot")
    leaf("alert-bot", alert_bot, "configure", "alerts-configure")
    leaf("alert-bot", alert_bot, "status", "alerts-status")
    leaf("alert-bot", alert_bot, "test", "alerts-test")

    _, heartbeat = group("heartbeat")
    leaf("heartbeat", heartbeat, "configure", "heartbeat-configure")
    leaf("heartbeat", heartbeat, "test", "heartbeat-test")

    _, management_bot = group("management-bot")
    leaf("management-bot", management_bot, "configure", "management-bot-configure")
    leaf("management-bot", management_bot, "status", "management-bot-status")
    leaf("management-bot", management_bot, "test", "management-bot-test")

    _, upstream = group("upstream")
    for action in ["users", "inbounds", "sync"]:
        leaf("upstream", upstream, action, action)
    reconcile = leaf("upstream", upstream, "reconcile", "reconcile")
    reconcile.add_argument("--confirm", action="store_true", dest="confirmed", help="Apply changes")

    _, user = group("user")
    _, personal = group("personal")
    masque = leaf("personal", personal, "masque", "personal-masque")
    masque.add_argument(
        "--binary",
        type=Path,
        default=operator_config().get("aether_binary"),
        help="Verified Aether executable (or configure aether_binary)",
    )
    masque.add_argument(
        "--state",
        type=Path,
        default=operator_config().get("masque_state"),
        help="Private identity directory (default: user data directory)",
    )
    masque.add_argument(
        "--port",
        type=int,
        default=int(operator_config().get("masque_port", "1819")),
        help="Loopback SOCKS port",
    )
    masque.add_argument("--ipv6", action="store_true", help="Use IPv6 instead of IPv4")
    masque.add_argument("--no-fragment", action="store_true", help="Try ordinary HTTP2 TLS")
    masque.add_argument(
        "--scan",
        choices=["turbo", "balanced", "thorough", "stealth", "ironclad"],
        default="balanced",
        help="Endpoint scan strategy (default: balanced)",
    )
    masque.add_argument(
        "--fresh", action="store_true", help="Scan instead of reusing a saved endpoint"
    )
    masque.add_argument("--register", action="store_true", help="Register WARP keys and exit")
    masque.add_argument("--register-proxy", help="Use a working loopback proxy only for --register")
    dnstt = leaf("personal", personal, "dnstt", "personal-dnstt")
    dnstt.add_argument(
        "--save-link", type=Path, required=True, help="New private profile JSON file"
    )
    user_create = leaf("user", user, "create", "user-create")
    user_create.add_argument("username", help="New Marzban username")
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
        "--protocols",
        nargs="+",
        choices=["vless", "vmess", "trojan", "shadowsocks"],
        help=argparse.SUPPRESS,
    )
    user_create.add_argument(
        "--inbounds", help="Comma-separated inbound numbers, all, or default (omitted: default)"
    )
    user_create.add_argument("--save-link", type=Path, help="New private JSON file for the URL")
    user_create.add_argument("--inbound-tags", nargs="+", help=argparse.SUPPRESS)

    attach = leaf("user", user, "attach", "create")
    attach.add_argument("username", help="Existing Marzban username")
    attach.add_argument("--name", help="Display name; defaults to Marzban username")
    attach.add_argument("--telegram", help="Unique Telegram username or numeric ID")
    attach.add_argument("--phone", help="Unique international phone number, for example +98912...")
    attach.add_argument("--profiles", nargs="+", choices=KINDS)
    attach.add_argument(
        "--save-link", type=Path, help="Explicit private local file, never overwritten"
    )

    user_update = leaf("user", user, "update", "user-update")
    user_update.add_argument("username", help="Marzban username")
    user_update.add_argument("--quota-gb", type=float, help="New quota; 0 means unlimited")
    user_update.add_argument("--days", type=int, help="Expiry from now; 0 means no expiry")
    user_update.add_argument("--status", choices=["active", "disabled"], help="Panel status")
    inbound = leaf("user", user, "inbounds", "user-inbounds")
    inbound.add_argument("username", nargs="?", help="Omit to list available inbounds")
    inbound.add_argument("--protocol", choices=["vless", "vmess", "trojan", "shadowsocks"])
    inbound.add_argument("--tags", nargs="*", help="Advanced: selected tags for --protocol")
    inbound.add_argument(
        "--select", help="Replace selection: comma-separated numbers, all, or default"
    )
    inbound.add_argument(
        "--confirm", action="store_true", dest="confirmed", help="Apply --select without prompting"
    )
    defaults = leaf("user", user, "defaults", "user-defaults")
    defaults.add_argument("--select", help="New defaults: comma-separated numbers or all")
    defaults.add_argument(
        "--confirm", action="store_true", dest="confirmed", help="Apply without prompting"
    )
    usage = leaf("user", user, "usage", "user-usage")
    usage.add_argument("username", help="Marzban username")
    reset = leaf("user", user, "reset-usage", "user-reset-usage")
    reset.add_argument("username", help="Marzban username")
    reset.add_argument("--confirm", action="store_true", dest="confirmed", help="Apply reset")

    _, panel_commands = group("panel")
    panel = leaf("panel", panel_commands, "open", "panel")
    panel.add_argument(
        "--port",
        type=int,
        default=int(operator_config().get("panel_port", "28080")),
        help="Local tunnel port",
    )
    panel.add_argument(
        "--no-browser", action="store_true", help="Print URL without opening browser"
    )
    bookmark = leaf("panel", panel_commands, "url", "panel-url")
    bookmark.add_argument("--save-link", type=Path, help="New private JSON file")

    _, customer = group("customer")
    listing = leaf("customer", customer, "list", "list")
    listing.add_argument("--limit", type=int, default=100, help="Rows, 1-100")
    listing.add_argument("--offset", type=int, default=0, help="Rows to skip")
    listing.add_argument("--history", action="store_true", help="Include revoked registrations")
    listing.add_argument("--brief", action="store_true", help="Only usernames and private names")
    listing.add_argument("--search", help="Filter username or private name (case-insensitive)")
    customer_update = leaf("customer", customer, "update", "customer-update")
    customer_update.add_argument(
        "customer", help="Customer ID, username, exact private name, Telegram or phone"
    )
    customer_update.add_argument("--name")
    customer_update.add_argument("--telegram")
    customer_update.add_argument("--phone")
    customer_update.add_argument("--clear-telegram", action="store_true")
    customer_update.add_argument("--clear-phone", action="store_true")
    for op in [
        "link",
        "configs",
        "config",
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
        command = leaf("customer", customer, op, op)
        command.add_argument(
            "customer", help="Customer ID, exact username/private name, Telegram handle/ID or phone"
        )
        if op == "config":
            command.add_argument("profile", help="Configuration ID or uniquely matching family")
        if op == "rename":
            command.add_argument("name", help="New private display name")
        if op == "remap":
            command.add_argument("username", help="Replacement upstream username")
        if op == "profiles":
            command.add_argument("profiles", nargs="+", choices=KINDS, help="Profile kinds")
        if op in {"revoke", "rotate-token"}:
            command.add_argument(
                "--confirm", action="store_true", dest="confirmed", help="Apply change"
            )
        if op == "link":
            command.add_argument("--info", action="store_true", help="Show the usage-page URL")
        if op in {"rotate-token", "link", "config"}:
            command.add_argument("--save-link", type=Path, help="New private JSON file")
    help_command = resources.add_parser(
        "help", help="Show complete help, or help for one resource/action path"
    )
    help_command.add_argument("command", nargs="*", metavar="COMMAND")
    help_command.set_defaults(operation="help")
    command_parsers[("help",)] = help_command
    p.command_parsers = command_parsers
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
        if set(item) == {"username", "name"}:
            print(safe(item["username"]), safe(item["name"]), sep="\t")
        elif "mapping" in item:
            print(
                safe(item["mapping"]["upstream_username"]),
                "\t".join(
                    safe(item.get(k, "")) for k in ["id", "telegram", "phone", "status", "name"]
                ),
                sep="\t",
            )
        else:
            print(json.dumps(item, ensure_ascii=False))


def pick_inbounds(args: argparse.Namespace) -> int:
    from keyholder.inbounds import profile_label, profile_summary, select_tags

    base = {"username": getattr(args, "username", None), "backend_id": args.backend_id}

    def call(fields: dict[str, Any]) -> Any:
        return request(
            args.host, {"operation": args.operation, "args": {**base, **fields}}, local=args.local
        )["result"]

    catalog = call({})
    if args.json and args.select is None:
        display(catalog, True)
        return 0
    if not args.json:
        print("Available inbounds ([x] selected; default plan for an omitted username):")
        for row in catalog["entries"]:
            print(
                f"{row['number']:2}. [{'x' if row['selected'] else ' '}] "
                + profile_label(row)
                + f" ({row['protocol']})"
            )
        print("Selected: " + profile_summary([r for r in catalog["entries"] if r["selected"]]))
    selection = args.select
    if selection is None:
        if not sys.stdin.isatty() or not base["username"]:
            return 0
        selection = input("Select numbers separated by commas (Enter cancels): ").strip()
        if not selection:
            return 0
    try:
        selected = select_tags(catalog["entries"], selection, catalog.get("default_tags", []))
    except ValueError as error:
        raise CLIError(str(error)) from None
    chosen = [row for tag in selected for row in catalog["entries"] if row["tag"] == tag]
    if not args.json:
        print("New selection: " + "; ".join(profile_label(row) for row in chosen))
        print(profile_summary(chosen))
    if not args.confirmed:
        if not sys.stdin.isatty():
            raise CLIError("Use --confirm to apply a noninteractive selection.")
        if input("Apply this selection? [y/N] ").strip().lower() != "y":
            return 0
    display(
        call({"selected_tags": selected, "revision": catalog["revision"], "confirmed": True}),
        args.json,
    )
    return 0


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
    supplied = list(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(normalize_argv(supplied))
    if args.operation == "help":
        if args.command:
            path = tuple(args.command)
            command_parser = p.command_parsers.get(path)
            if command_parser is None:
                p.error("Unknown command path; use 'keyholder help' to list resources.")
            command_parser.print_help()
        else:
            p.print_help()
        return 0
    if args.operation == "personal-masque":
        from keyholder.personal import run_masque

        if args.local or args.json:
            p.error("MASQUE runs interactively on your workstation, without --local/--json.")
        try:
            return run_masque(
                args.binary,
                args.state,
                args.port,
                args.ipv6,
                args.no_fragment,
                scan=args.scan,
                fresh=args.fresh,
                register=args.register,
                register_proxy=args.register_proxy,
            )
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
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
    if (
        args.operation
        in {
            "create",
            "remap",
            "user-create",
            "user-update",
            "user-inbounds",
            "user-usage",
            "user-reset-usage",
        }
        and not (args.operation == "user-inbounds" and args.username is None)
        and not re.fullmatch(r"[A-Za-z0-9_]{3,32}", args.username)
    ):
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
    secret = args.operation in {
        "create",
        "user-create",
        "link",
        "config",
        "rotate-token",
        "panel-url",
        "personal-dnstt",
    }
    destination = getattr(args, "save_link", None)
    if secret and not destination and (not sys.stdout.isatty() or args.json):
        p.error("Links require an interactive terminal or explicit --save-link private file.")
    fd = None
    try:
        if args.operation == "user-defaults":
            return pick_inbounds(args)
        if args.operation == "user-inbounds":
            if not args.username and (args.select or args.protocol or args.tags is not None):
                raise CLIError(
                    "Specify a username to edit, or use 'user defaults' for future users."
                )
            if bool(args.protocol) != (args.tags is not None) or (
                args.protocol and args.select is not None
            ):
                raise CLIError("Use --protocol with --tags, or the numbered picker.")
            if not args.protocol:
                return pick_inbounds(args)
        if args.operation == "panel":
            return run_panel(args)
        if destination:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        payload = {
            "operation": args.operation,
            "args": {
                k: v
                for k, v in vars(args).items()
                if k
                not in {
                    "operation",
                    "resource",
                    "action",
                    "command",
                    "host",
                    "json",
                    "save_link",
                    "local",
                    "info",
                }
            },
        }
        if args.operation == "tls-configure":
            if not sys.stdin.isatty():
                p.error("TLS configuration requires an interactive terminal.")
            payload["args"]["token"] = getpass.getpass("Scoped Cloudflare DNS API token: ")
        if args.operation == "alerts-configure":
            if not sys.stdin.isatty():
                p.error("Telegram configuration requires an interactive terminal.")
            payload["args"]["bot_token"] = getpass.getpass("Alert bot token: ")
            input("Send /start to the alert bot in a private chat, then press Enter here: ")
            payload["args"]["chat_id"] = ""
        if args.operation == "heartbeat-configure":
            if not sys.stdin.isatty():
                p.error("Heartbeat configuration requires an interactive terminal.")
            payload["args"]["heartbeat_url"] = getpass.getpass("Better Stack heartbeat URL: ")
        if args.operation == "management-bot-configure":
            if not sys.stdin.isatty():
                p.error("Management bot configuration requires an interactive terminal.")
            payload["args"]["bot_token"] = getpass.getpass("Management bot token: ")
            input("Send /start to the management bot in a private chat, then press Enter here: ")
            payload["args"]["chat_id"] = ""
        result = (
            request(args.host, payload, local=True) if args.local else request(args.host, payload)
        )["result"]
        if secret:
            if args.operation == "config":
                credentials = result
            elif args.operation == "personal-dnstt":
                credentials = result
            elif args.operation == "panel-url":
                credentials = {"panel_url": result["panel_url"], "active": result["active"]}
            else:
                credentials = {
                    "customer_id": result["customer"]["id"],
                    "subscription_url": result["subscription_url"],
                }
            if getattr(args, "info", False):
                credentials["usage_url"] = result["subscription_url"] + "?format=info"
            if fd is not None:
                with os.fdopen(fd, "w") as file:
                    fd = None
                    file.write(json.dumps(credentials, indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                print("Private link file saved. Keep it in secure storage.")
            elif args.operation == "config":
                print("Configuration:", result["name"])
                print("URI:", result["config_uri"])
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
