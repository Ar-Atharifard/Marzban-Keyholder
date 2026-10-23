"""Close domestic customer access when authenticated panel heartbeats stop."""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

HEARTBEAT = re.compile(r'"POST /ping HTTP/[0-9.]+" 200(?:\s|$)')


if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


def heartbeat_age(records: str, now: float) -> float | None:
    latest = None
    for line in records.splitlines():
        try:
            row = json.loads(line)
            stamp = int(row["__MONOTONIC_TIMESTAMP"]) / 1_000_000
            if HEARTBEAT.search(row.get("MESSAGE", "")) and 0 <= stamp <= now:
                latest = max(latest or 0, stamp)
        except (ValueError, KeyError, TypeError):
            continue
    return None if latest is None else now - latest


def main() -> None:
    options = component_settings(
        "domestic_guard",
        {
            "armed_file": "/etc/keyholder-domestic/armed",
            "state_file": "/var/lib/keyholder-domestic/guard.json",
            "node_service": "marzban-node.service",
            "gateway_service": "haproxy.service",
            "journal_window_minutes": 6,
            "journal_records": 2000,
            "heartbeat_max_age_seconds": 300,
        },
    )
    if not Path(options["armed_file"]).exists():
        return
    journal = subprocess.run(
        [
            "journalctl",
            "-u",
            options["node_service"],
            "-b",
            "--since=-" + str(options["journal_window_minutes"]) + "min",
            "-n",
            str(options["journal_records"]),
            "-o",
            "json",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    age = heartbeat_age(journal.stdout, time.monotonic())
    permitted = age is not None and age < options["heartbeat_max_age_seconds"]
    active = (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", options["gateway_service"]],
            check=False,
        ).returncode
        == 0
    )
    if active != permitted:
        subprocess.run(
            ["systemctl", "start" if permitted else "stop", options["gateway_service"]],
            check=True,
            timeout=30,
        )
        print(
            "Domestic entry reopened"
            if permitted
            else "Domestic entry closed: panel heartbeat stale"
        )
    status = Path(options["state_file"])
    status.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = status.with_suffix(".tmp")
    temporary.write_text(json.dumps({"heartbeat_age_seconds": age, "entry_permitted": permitted}))
    temporary.replace(status)


if __name__ == "__main__":
    main()
