"""Close domestic customer access when authenticated panel heartbeats stop."""

import json
import re
import subprocess
import time
from pathlib import Path

HEARTBEAT = re.compile(r'"POST /ping HTTP/[0-9.]+" 200(?:\s|$)')


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
    if not Path("/etc/keyholder-domestic/armed").exists():
        return
    journal = subprocess.run(
        [
            "journalctl",
            "-u",
            "marzban-node.service",
            "-b",
            "--since=-6min",
            "-n",
            "2000",
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
    permitted = age is not None and age < 300
    active = (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "haproxy.service"],
            check=False,
        ).returncode
        == 0
    )
    if active != permitted:
        subprocess.run(
            ["systemctl", "start" if permitted else "stop", "haproxy.service"],
            check=True,
            timeout=30,
        )
        print(
            "Domestic entry reopened"
            if permitted
            else "Domestic entry closed: panel heartbeat stale"
        )
    status = Path("/var/lib/keyholder-domestic/guard.json")
    status.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = status.with_suffix(".tmp")
    temporary.write_text(json.dumps({"heartbeat_age_seconds": age, "entry_permitted": permitted}))
    temporary.replace(status)


if __name__ == "__main__":
    main()
