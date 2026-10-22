#!/usr/bin/python3
"""Export the fixed domestic recovery file set over the restricted SSH command."""

import sys
import tarfile
from pathlib import Path

FILES = [
    "opt/marzban-node",
    "var/cache/keyholder-node-wheels",
    "usr/local/bin/rathole",
    "usr/local/bin/frps",
    "etc/keyholder-frp",
    "etc/keyholder-forward",
    "etc/keyholder-backhaul",
    "etc/systemd/system/keyholder-forward-client.service",
    "usr/local/lib/keyholder-admin/backhaul_probe.py",
    "etc/systemd/system/keyholder-frp-server.service",
    "usr/local/lib/keyholder-admin/domestic_guard.py",
    "usr/local/lib/keyholder-admin/backhaul_guard.py",
    "etc/systemd/system/keyholder-backhaul-guard.service",
    "etc/systemd/system/keyholder-backhaul-guard.timer",
    "usr/local/lib/keyholder-admin/gate_status.py",
    "usr/local/lib/keyholder-admin/monitor.py",
    "usr/local/libexec/keyholder-gate-backup",
    "usr/local/libexec/keyholder-gate-readonly",
    "etc/keyholder-rathole/server.toml",
    "etc/marzban-node/node.env",
    "etc/haproxy/haproxy.cfg",
    "etc/keyholder-domestic/armed",
    "etc/ufw",
    "var/lib/marzban-node/ssl_cert.pem",
    "var/lib/marzban-node/ssl_key.pem",
    "var/lib/marzban-node/ssl_client_cert.pem",
    "etc/systemd/system/marzban-node.service",
    "etc/systemd/system/keyholder-rathole-server.service",
    "etc/systemd/system/keyholder-domestic-guard.service",
    "etc/systemd/system/keyholder-domestic-guard.timer",
    "etc/systemd/system/keyholder-domestic-close.service",
]


def safe_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if not (member.isfile() or member.isdir()):
        return None
    if any(part in {".venv", "__pycache__", ".git"} for part in Path(member.name).parts):
        return None
    return member


if __name__ == "__main__":
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
        for name in FILES:
            path = Path("/", name)
            if path.exists():
                archive.add(path, arcname=name, filter=safe_member)
