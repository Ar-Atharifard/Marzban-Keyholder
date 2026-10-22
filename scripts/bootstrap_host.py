#!/usr/bin/python3
"""Transactional SSH/UFW bootstrap for an explicitly empty Ubuntu host."""

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

STATE = Path("/var/lib/keyholder-bootstrap")
SSH = Path("/etc/ssh")
TIMER = "keyholder-bootstrap-rollback"


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def validate(plan: dict[str, Any]) -> None:
    if type(plan["old_port"]) is not int or not 1 <= plan["old_port"] <= 65535:
        raise ValueError("Invalid initial SSH port")
    for rule in plan["rules"]:
        if set(rule) != {"port", "source"}:
            raise ValueError("Only explicit TCP port/source rules are supported")
        if type(rule["port"]) is not int or not 1 <= rule["port"] <= 65535:
            raise ValueError("Invalid TCP port")
        if rule["port"] == plan["old_port"] and rule["port"] != 2222:
            raise ValueError("Do not retain the initial SSH port in service rules")
        if rule["source"] != "any":
            ipaddress.ip_network(rule["source"], strict=False)


def ssh_config(final: bool, old_port: int) -> None:
    paths = [SSH / "sshd_config", *sorted((SSH / "sshd_config.d").glob("*.conf"))]
    for path in paths:
        text = path.read_text()
        if re.search(r"^\s*Match\s", text, re.M | re.I):
            raise ValueError("Review conditional SSH configuration before bootstrap")
        text = re.sub(r"^\s*Port\s+.*$", "", text, flags=re.M | re.I)
        if path.name == "sshd_config":
            ports = sorted({2222} if final else {old_port, 2222})
            policy = "".join(f"Port {port}\n" for port in ports)
            if final:
                policy += (
                    "PermitRootLogin no\nPasswordAuthentication no\n"
                    "KbdInteractiveAuthentication no\nPubkeyAuthentication yes\n"
                    "AuthenticationMethods publickey\n"
                )
            text = policy + text
        path.write_text(text)
    run("/usr/sbin/sshd", "-t")
    run("systemctl", "reload", "ssh")


def rollback() -> None:
    if not (STATE / "armed").exists():
        return
    for name in ["ufw", "ssh"]:
        source = STATE / name
        destination = Path("/etc") / name
        if name == "ssh":
            shutil.copy2(source / "sshd_config", destination / "sshd_config")
            shutil.rmtree(destination / "sshd_config.d")
            shutil.copytree(source / "sshd_config.d", destination / "sshd_config.d")
        else:
            shutil.copytree(source, destination, dirs_exist_ok=True)
    shutil.copy2(STATE / "ufw-default", "/etc/default/ufw")
    run("/usr/sbin/sshd", "-t")
    run("systemctl", "reload", "ssh")
    run("ufw", "--force", "enable" if (STATE / "ufw-active").exists() else "disable")
    (STATE / "armed").unlink()


def prepare(plan: dict[str, Any]) -> None:
    validate(plan)
    if STATE.exists():
        raise ValueError("Bootstrap checkpoint exists; inspect it before retrying")
    if subprocess.run(["systemctl", "is-active", "--quiet", "ssh.socket"]).returncode == 0:
        raise ValueError("Socket-activated SSH requires a separate reviewed transition")
    for unit in ["netfilter-persistent", "nftables"]:
        if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
            raise ValueError("Another firewall manager is active")
    for name in ["user.rules", "user6.rules"]:
        if re.search(r"^### tuple ###", (Path("/etc/ufw") / name).read_text(), re.M):
            raise ValueError("Existing firewall rules require review; empty host required")
    for command in ["iptables-save", "ip6tables-save"]:
        if any(line.startswith("-A ") and "ufw-" not in line for line in run(command).splitlines()):
            raise ValueError("Non-UFW packet-filter rules require review")
    # Refuse conditional policies before creating the rollback checkpoint.
    for path in [SSH / "sshd_config", *sorted((SSH / "sshd_config.d").glob("*.conf"))]:
        if re.search(r"^\s*Match\s", path.read_text(), re.M | re.I):
            raise ValueError("Conditional SSH policy requires review")
    STATE.mkdir(mode=0o700)
    (STATE / "ssh").mkdir(mode=0o700)
    shutil.copy2(SSH / "sshd_config", STATE / "ssh/sshd_config")
    shutil.copytree(SSH / "sshd_config.d", STATE / "ssh/sshd_config.d")
    shutil.copytree("/etc/ufw", STATE / "ufw")
    shutil.copy2("/etc/default/ufw", STATE / "ufw-default")
    if "Status: active" in run("ufw", "status"):
        (STATE / "ufw-active").touch(mode=0o600)
    (STATE / "plan.json").write_text(json.dumps(plan))
    (STATE / "armed").touch(mode=0o600)
    run(
        "systemd-run",
        "--unit=" + TIMER,
        "--on-active=10m",
        "/usr/bin/python3",
        "/usr/local/lib/keyholder-recovery/bootstrap_host.py",
        "rollback",
    )
    try:
        default = Path("/etc/default/ufw")
        default.write_text(re.sub(r"^IPV6=.*$", "IPV6=yes", default.read_text(), flags=re.M))
        run("ufw", "default", "deny", "incoming")
        run("ufw", "default", "allow", "outgoing")
        run("ufw", "default", "deny", "routed")
        for port in sorted({plan["old_port"], 2222}):
            run("ufw", "allow", str(port) + "/tcp")
        for rule in plan["rules"]:
            run(
                "ufw",
                "allow",
                "proto",
                "tcp",
                "from",
                rule["source"],
                "to",
                "any",
                "port",
                str(rule["port"]),
            )
        run("ufw", "--force", "enable")
        ssh_config(False, plan["old_port"])
    except Exception:
        rollback()
        raise


def finish() -> None:
    if not (STATE / "armed").exists():
        raise ValueError("No armed transition")
    plan = json.loads((STATE / "plan.json").read_text())
    try:
        ssh_config(True, plan["old_port"])
        policy = run("/usr/sbin/sshd", "-T")
        if [line for line in policy.splitlines() if line.startswith("port ")] != ["port 2222"]:
            raise ValueError("Unexpected SSH listener remains")
        for value in [
            "port 2222",
            "permitrootlogin no",
            "passwordauthentication no",
            "kbdinteractiveauthentication no",
            "authenticationmethods publickey",
        ]:
            if value not in policy.splitlines():
                raise ValueError("Effective SSH policy differs from requested policy")
        if plan["old_port"] != 2222:
            run("ufw", "--force", "delete", "allow", str(plan["old_port"]) + "/tcp")
    except Exception:
        rollback()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "finish", "commit", "rollback"])
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if args.plan is None:
                raise ValueError("Plan required")
            prepare(json.loads(args.plan.read_text()))
        elif args.action == "finish":
            finish()
        elif args.action == "rollback":
            rollback()
        else:
            (STATE / "armed").unlink()
            run("systemctl", "stop", TIMER + ".timer")
        print("Host security operation completed.")
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise SystemExit(
            "Host security operation failed; inspect console and rollback checkpoint."
        ) from None
