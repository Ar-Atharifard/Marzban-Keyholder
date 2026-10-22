#!/usr/bin/env python3
"""Run the foreign or domestic recovery workflow from one private replacement plan."""

import argparse
import base64
import hashlib
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]  # Provided by the controller's ansible-core.

if TYPE_CHECKING or __package__:
    from scripts.bootstrap_host import validate
else:
    from bootstrap_host import validate

ROOT = Path(__file__).resolve().parents[1]


def inventory(plan: dict[str, Any], ssh_config: Path) -> dict[str, Any]:
    """Reuse the existing recovery defaults; expose only deployment facts to operators."""
    key = Path(plan["admin_key_file"]).expanduser().resolve()
    if not key.is_file():
        raise ValueError("Administrator private key file is missing")
    public = Path(str(key) + ".pub").read_text().strip()
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\n]*)?", public):
        raise ValueError("An Ed25519 administrator public key is required")
    if any(char in str(key) for char in '\n\r"'):
        raise ValueError("Invalid key path")
    hostname = plan["subscription_hostname"]
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", hostname):
        raise ValueError("Use a subscription hostname without URL or path")
    for role in ["foreign", "domestic"]:
        node = plan[role]
        for version in [4, 6]:
            for name in [f"ipv{version}", f"previous_ipv{version}"]:
                address = ipaddress.ip_address(node[name])
                if address.version != version:
                    raise ValueError("Replacement and previous addresses must preserve IP family")
                node[name] = str(address)
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", node.get("ssh_user", "root")):
            raise ValueError("Invalid initial SSH user")
        if not 1 <= int(node.get("ssh_port", 22)) <= 65535:
            raise ValueError("Invalid initial SSH port")
    foreign, domestic = plan["foreign"], plan["domestic"]
    if foreign["ipv4"] == domestic["ipv4"] or foreign["ipv6"] == domestic["ipv6"]:
        raise ValueError("Select two distinct replacement hosts")
    defaults = yaml.safe_load((ROOT / "deploy/ansible/inventory/example.yml").read_text())
    recovery = defaults["all"]["children"]["recovery_targets"]["vars"]
    recovery.update(
        recovery_target_is_disposable=True,
        recovery_environment="production",
        recovery_security_validated=True,
        recovery_addresses_reviewed=True,
        recovery_address_map={foreign[f"previous_ipv{v}"]: foreign[f"ipv{v}"] for v in [4, 6]},
        recovery_peer_address_map={
            domestic[f"previous_ipv{v}"]: domestic[f"ipv{v}"] for v in [4, 6]
        },
        recovery_domestic_peers_reviewed=True,
        recovery_activate_jobs=False,
        recovery_keep_repository_credentials=True,
    )
    domestic_defaults = yaml.safe_load(
        (ROOT / "deploy/ansible/inventory/domestic.example.yml").read_text()
    )["all"]["children"]["domestic_targets"]["vars"]
    domestic_defaults.update(
        domestic_target_is_empty=True,
        domestic_security_validated=True,
        domestic_console_ready=True,
        domestic_foreign_ipv4=foreign["ipv4"],
        domestic_peer_address_map={
            **recovery["recovery_address_map"],
            **recovery["recovery_peer_address_map"],
        },
    )
    groups: dict[str, Any] = {}
    for role, group, values in [
        ("foreign", "recovery_targets", recovery),
        ("domestic", "domestic_targets", domestic_defaults),
    ]:
        node = plan[role]
        rules = (
            [
                {"port": p, "source": "any"}
                for p in node.get("emergency_ports", [8443, 9443, 10443, 11443])
            ]
            + [{"port": 24432, "source": domestic["ipv6"]}]
            if role == "foreign"
            else [{"port": 443, "source": "any"}]
            + [{"port": p, "source": foreign["ipv4"]} for p in [62050, 62051, 24430]]
        )
        values.update(
            host_tcp_rules=rules,
            host_cloudflare_origin_ports=node.get(
                "cloudflare_origin_ports", [80, 443, 2053] if role == "foreign" else []
            ),
        )
        validate(
            {
                "old_port": int(node.get("ssh_port", 22)),
                "rules": rules,
                "origin_ports": values["host_cloudflare_origin_ports"],
            }
        )
        groups[group] = {
            "hosts": {
                f"replacement-{role}": {
                    "ansible_host": node["ipv4"],
                    "ansible_user": node.get("ssh_user", "root"),
                    "ansible_port": int(node.get("ssh_port", 22)),
                    "ansible_ssh_private_key_file": str(key),
                }
            },
            "vars": values,
        }
    groups["host_targets"] = {"children": {"recovery_targets": {}, "domestic_targets": {}}}
    return {
        "all": {
            "children": groups,
            "vars": {
                "host_target_is_empty": True,
                "host_console_ready": True,
                "host_rules_reviewed": True,
                "host_admin_user": "khadmin",
                "host_admin_public_key": public,
                "host_identity_file": str(key),
                "replacement_ssh_config": str(ssh_config),
                "replacement_subscription_host": hostname,
                "replacement_foreign_ipv4": foreign["ipv4"],
                "replacement_domestic_ipv4": domestic["ipv4"],
                "replacement_domestic_ipv6": domestic["ipv6"],
            },
        }
    }


def pin_host(node: dict[str, Any], known_hosts: Path) -> None:
    host, port = node["ipv4"], int(node.get("ssh_port", 22))
    output = subprocess.check_output(
        ["ssh-keyscan", "-T", "10", "-p", str(port), "-t", "ed25519", host],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    rows = [row.split() for row in output.splitlines() if not row.startswith("#")]
    if len(rows) != 1 or len(rows[0]) != 3 or rows[0][1] != "ssh-ed25519":
        raise ValueError("Could not read the initial SSH host key")
    name = host if port == 22 else f"[{host}]:{port}"
    key = " ".join(rows[0][1:])
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(rows[0][2], validate=True)).digest()
    ).decode().rstrip("=")
    existing = subprocess.run(
        ["ssh-keygen", "-F", name, "-f", str(known_hosts)],
        text=True,
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0:
        if any(line.endswith(" " + key) for line in existing.stdout.splitlines()):
            return
        print("Stored SSH identity differs. A replacement needs fresh console verification.")
    answer = input(
        f"Compare {host}:{port} with its provider console.\n"
        f"Host key: {fingerprint}\nType the full verified SHA256 fingerprint: "
    ).strip()
    if answer != fingerprint:
        raise ValueError("Host identity was not confirmed")
    if existing.returncode == 0:
        subprocess.run(
            ["ssh-keygen", "-R", name, "-f", str(known_hosts)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with known_hosts.open("a") as out:
        out.write(f"{name} {key}\n")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"foreign", "domestic"}:
        raise SystemExit("Use deploy/restore-foreign or deploy/restore-domestic.")
    role = sys.argv[1]
    parser = argparse.ArgumentParser(prog=f"./deploy/restore-{role}", description=__doc__)
    parser.add_argument(
        "plan",
        type=Path,
        nargs="?",
        default=ROOT / ".private/replacement.yml",
        help="Private plan (default: .private/replacement.yml)",
    )
    parser.add_argument(
        "--plan-only", action="store_true", help="Validate/render without connecting"
    )
    args = parser.parse_args(sys.argv[2:])
    args.role = role
    plan = yaml.safe_load(args.plan.read_text())
    state = (
        ROOT
        / ".private"
        / ("replacement-" + hashlib.sha256(str(args.plan.resolve()).encode()).hexdigest()[:12])
    )
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = state / "ssh.config"
    data = inventory(plan, config)
    path = state / "inventory.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    path.chmod(0o600)
    key = data["all"]["vars"]["host_identity_file"]
    config.write_text(
        "".join(
            f"Host replacement-{role}\n HostName {plan[role]['ipv4']}\n User khadmin\n"
            f' Port 2222\n IdentityFile "{key}"\n IdentitiesOnly yes\n StrictHostKeyChecking yes\n'
            " ClearAllForwardings yes\n"
            for role in ["foreign", "domestic"]
        )
    )
    config.chmod(0o600)
    if args.plan_only:
        print(f"Validated private deployment inventory: {path}")
        return
    group = "recovery_targets" if args.role == "foreign" else "domestic_targets"
    rules = data["all"]["children"][group]["vars"]
    print(f"Target: {args.role} {plan[args.role]['ipv4']} / {plan[args.role]['ipv6']}")
    print("Final access: khadmin, SSH key only, port 2222. Service TCP allowances:")
    for rule in rules["host_tcp_rules"]:
        print(f"  {rule['port']} from {rule['source']}")
    if rules["host_cloudflare_origin_ports"]:
        print(f"  {rules['host_cloudflare_origin_ports']} from official Cloudflare ranges only")
    if (
        input(
            f"Fresh {args.role} target: {plan[args.role]['ipv4']}. "
            "Provider console open and usable? Type CONSOLE: "
        ).strip()
        != "CONSOLE"
    ):
        raise ValueError("Independent console required before SSH/firewall changes")
    pin_host(plan[args.role], Path.home() / ".ssh/known_hosts")
    runner = Path(sys.executable).with_name("ansible-playbook")
    os.execv(
        str(runner),
        [
            str(runner),
            "-i",
            str(path),
            str(ROOT / f"deploy/ansible/playbooks/deploy-{args.role}.yml"),
            "--ask-become-pass",
        ],
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit(
            "Deployment stopped. Check the private plan, verified SSH access and target state; "
            "do not rerun a partial restore blindly."
        ) from None
