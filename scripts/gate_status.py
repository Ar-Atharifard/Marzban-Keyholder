#!/usr/bin/python3
"""Read-only domestic-node telemetry for the central monitor."""

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from scripts.monitor import system_metrics
else:
    from monitor import system_metrics


def main() -> None:
    units = [
        "ssh",
        "ufw",
        "marzban-node",
        "keyholder-rathole-server",
        "keyholder-domestic-guard.timer",
        "haproxy",
    ]
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
    print(json.dumps({"metrics": system_metrics(), "services": services, "guard": guard}))


if __name__ == "__main__":
    main()
