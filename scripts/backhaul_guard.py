#!/usr/bin/python3
"""Recover a stalled Rathole listener only while the alternate path is healthy."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING or __package__:
    from scripts.gate_status import backhaul_status
else:
    from gate_status import backhaul_status


def advance(
    paths: dict[str, str], state: dict[str, Any], now: float, permitted: bool
) -> tuple[dict[str, Any], bool]:
    failures = 0 if paths.get("rathole", "").startswith("UP") else state.get("failures", 0) + 1
    restart = (
        permitted
        and failures >= 3
        and any(paths.get(name, "").startswith("UP") for name in ["frp", "forward"])
        and now - state.get("last_restart", 0) >= 1800
    )
    return {
        "failures": 0 if restart else failures,
        "last_restart": now if restart else state.get("last_restart", 0),
        "checked_at": now,
    }, restart


def main() -> None:
    root = Path("/var/lib/keyholder-domestic")
    path = root / "backhaul-health.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    guard = json.loads((root / "guard.json").read_text())
    if not guard["entry_permitted"]:
        return
    try:
        paths = backhaul_status()
    except OSError:
        return
    active = (
        subprocess.run(
            ["systemctl", "is-active", "keyholder-rathole-server"],
            capture_output=True,
            timeout=5,
        ).returncode
        == 0
    )
    state, restart = advance(paths, state, time.time(), active and guard["entry_permitted"])
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(state) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    if restart:
        subprocess.run(
            ["systemctl", "try-restart", "keyholder-rathole-server"], check=True, timeout=20
        )
        print("Rathole listener restarted after three failed probes; alternate backhaul healthy")


if __name__ == "__main__":
    main()
