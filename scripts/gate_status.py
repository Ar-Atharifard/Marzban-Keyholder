#!/usr/bin/python3
"""Read-only domestic-node telemetry for the central monitor."""

import csv
import io
import json
import socket
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from scripts.monitor import system_metrics
else:
    from monitor import system_metrics


def backhaul_status() -> dict[str, str]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect("/run/haproxy/keyholder.sock")
        client.sendall(b"show stat\n")
        data = bytearray()
        while chunk := client.recv(65536):
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise ValueError("Oversized gateway statistics")
    rows = csv.DictReader(io.StringIO(data.decode().lstrip("# ")))
    return {
        row["svname"]: row["status"]
        for row in rows
        if row.get("pxname") == "foreign_backhaul_paths" and row.get("svname") in {"rathole", "frp"}
    }


def main() -> None:
    units = [
        "ssh",
        "ufw",
        "marzban-node",
        "keyholder-rathole-server",
        "keyholder-domestic-guard.timer",
        "haproxy",
    ]
    if Path("/etc/systemd/system/keyholder-frp-server.service").exists():
        units.extend(["keyholder-frp-server", "keyholder-backhaul-guard.timer"])
    services = {}
    for unit in units:
        response = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        services[unit] = response.stdout.strip()
    guard = json.loads(Path("/var/lib/keyholder-domestic/guard.json").read_text())
    result = {"metrics": system_metrics(), "services": services, "guard": guard}
    if Path("/etc/keyholder-frp/server.toml").exists():
        try:
            result["backhauls"] = backhaul_status()
        except (OSError, ValueError):
            result["backhauls"] = {}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
