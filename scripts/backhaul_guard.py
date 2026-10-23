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


if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


def guard_settings() -> dict[str, Any]:
    return component_settings(
        "backhaul_guard",
        {
            "failure_threshold": 3,
            "cooldown_seconds": 1800,
            "state_directory": "/var/lib/keyholder-domestic",
            "target_service": "keyholder-rathole-server",
            "target_path": "rathole",
            "alternate_paths": ["frp", "forward"],
        },
    )


def advance(
    paths: dict[str, str], state: dict[str, Any], now: float, permitted: bool
) -> tuple[dict[str, Any], bool]:
    policy = guard_settings()
    failures = (
        0 if paths.get(policy["target_path"], "").startswith("UP") else state.get("failures", 0) + 1
    )
    restart = (
        permitted
        and failures >= policy["failure_threshold"]
        and any(paths.get(name, "").startswith("UP") for name in policy["alternate_paths"])
        and now - state.get("last_restart", 0) >= policy["cooldown_seconds"]
    )
    return {
        "failures": 0 if restart else failures,
        "last_restart": now if restart else state.get("last_restart", 0),
        "checked_at": now,
    }, restart


def main() -> None:
    options = guard_settings()
    root = Path(options["state_directory"])
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
            ["systemctl", "is-active", options["target_service"]],
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
            ["systemctl", "try-restart", options["target_service"]], check=True, timeout=20
        )
        print("Backhaul listener restarted after configured failures; alternate path healthy")


if __name__ == "__main__":
    main()
