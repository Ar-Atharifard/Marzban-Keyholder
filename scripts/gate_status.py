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


if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


OPTIONS = component_settings(
    "gate_status",
    {
        "socket": "/run/haproxy/keyholder.sock",
        "socket_timeout_seconds": 2,
        "backhaul_backend": "foreign_backhaul_paths",
        "backhaul_paths": ["rathole", "frp", "forward"],
        "guard_file": "/var/lib/keyholder-domestic/guard.json",
        "units": [
            "ssh",
            "ufw",
            "marzban-node",
            "keyholder-rathole-server",
            "keyholder-domestic-guard.timer",
            "haproxy",
        ],
        "optional_units": {
            "/etc/systemd/system/keyholder-frp-server.service": [
                "keyholder-frp-server",
                "keyholder-backhaul-guard.timer",
            ],
            "/etc/systemd/system/keyholder-forward-client.service": ["keyholder-forward-client"],
        },
        "backhaul_config": "/etc/keyholder-frp/server.toml",
    },
)


def backhaul_status() -> dict[str, str]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(OPTIONS["socket_timeout_seconds"])
        client.connect(OPTIONS["socket"])
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
        if row.get("pxname") == OPTIONS["backhaul_backend"]
        and row.get("svname") in OPTIONS["backhaul_paths"]
    }


def main() -> None:
    units = list(OPTIONS["units"])
    for file, extra_units in OPTIONS["optional_units"].items():
        if Path(file).exists():
            units.extend(extra_units)
    services = {}
    for unit in units:
        response = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        services[unit] = response.stdout.strip()
    guard = json.loads(Path(OPTIONS["guard_file"]).read_text())
    result = {"metrics": system_metrics(), "services": services, "guard": guard}
    if Path(OPTIONS["backhaul_config"]).exists():
        try:
            result["backhauls"] = backhaul_status()
        except (OSError, ValueError):
            result["backhauls"] = {}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
