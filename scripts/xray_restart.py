#!/usr/bin/env python3
"""Configure and run an optional, exit-only Xray restart schedule (Python 3.10+)."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TIMER = "keyholder-xray-restart.timer"
SERVICE = "keyholder-xray-restart.service"


def load_config(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("Restart config must not be a symlink")
    stat = path.stat()
    if os.geteuid() == 0 and (stat.st_uid != 0 or stat.st_mode & 0o077):
        raise ValueError("Restart config must be root-owned and mode 0600")
    config = json.loads(path.read_text())
    fields = {
        "enabled",
        "on_calendar",
        "target_service",
        "xray_binary",
        "xray_config",
        "asset_directory",
        "listeners",
        "readiness_timeout_seconds",
        "command_timeout_seconds",
    }
    if not isinstance(config, dict) or set(config) != fields:
        raise ValueError("Restart config fields must match the documented schema")
    if type(config["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", config["target_service"]):
        raise ValueError("Invalid target service")
    if config["target_service"] == SERVICE:
        raise ValueError("Cannot restart the scheduler itself")
    for field in ["xray_binary", "xray_config", "asset_directory"]:
        safe_path(config[field])
    calendar = config["on_calendar"]
    if (
        not isinstance(calendar, str)
        or not calendar
        or any(ord(c) < 32 or c == "%" for c in calendar)
    ):
        raise ValueError("Invalid calendar expression")
    for field in ["readiness_timeout_seconds", "command_timeout_seconds"]:
        if type(config[field]) not in (int, float) or not 1 <= config[field] <= 60:
            raise ValueError("Timeouts must be between 1 and 60 seconds")
    if not isinstance(config["listeners"], list) or not config["listeners"]:
        raise ValueError("At least one readiness listener is required")
    for listener in config["listeners"]:
        if (
            not isinstance(listener, dict)
            or set(listener) != {"host", "port"}
            or not ipaddress.ip_address(listener["host"]).is_loopback
            or type(listener["port"]) is not int
            or not 1 <= listener["port"] <= 65535
        ):
            raise ValueError("Readiness listeners must use loopback IPs and valid ports")
    return config


def safe_path(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
        raise ValueError("Expected an absolute path without shell or systemd substitutions")
    return value


def checked(argv: list[str], timeout: float = 10, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError("Restart operation failed: " + Path(argv[0]).name)
    return result.stdout.strip()


def active_pid(config: dict[str, Any]) -> int:
    pid = int(checked(["systemctl", "show", config["target_service"], "-p", "MainPID", "--value"]))
    if (
        pid <= 0
        or Path("/proc", str(pid), "exe").resolve() != Path(config["xray_binary"]).resolve()
    ):
        raise RuntimeError("Target service is not running the configured Xray binary")
    args = Path("/proc", str(pid), "cmdline").read_bytes().decode().split("\0")
    if "-config" not in args or args[args.index("-config") + 1] != config["xray_config"]:
        raise RuntimeError("Target service is not using the configured Xray config")
    return pid


def restart(config: dict[str, Any], *, check_only: bool = False) -> None:
    active_pid(config)
    checked(
        [config["xray_binary"], "run", "-test", "-config", config["xray_config"]],
        config["command_timeout_seconds"],
        {**os.environ, "XRAY_LOCATION_ASSET": config["asset_directory"]},
    )
    if check_only or not config["enabled"]:
        print("Xray configuration and target identity valid; no restart performed.")
        return
    checked(["systemctl", "restart", config["target_service"]], config["command_timeout_seconds"])
    deadline = time.monotonic() + config["readiness_timeout_seconds"]
    while time.monotonic() < deadline:
        try:
            active_pid(config)
            for listener in config["listeners"]:
                with socket.create_connection((listener["host"], listener["port"]), timeout=0.25):
                    pass
            print("Scheduled Xray exit restart complete; listeners ready.")
            return
        except (OSError, RuntimeError, ValueError):
            time.sleep(0.1)
    raise RuntimeError("Xray exit listener readiness failed after restart")


def atomic_write(path: Path, content: str) -> None:
    fd, name = tempfile.mkstemp(prefix=".xray-restart-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def apply(config: dict[str, Any], path: Path, unit_dir: Path) -> None:
    safe_path(str(path))
    safe_path(str(Path(__file__).resolve()))
    checked(["systemd-analyze", "calendar", config["on_calendar"]])
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = f"""[Unit]
Description=Optional scheduled Xray exit restart
OnFailure=keyholder-monitor.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {Path(__file__).resolve()} run --config {path}
TimeoutStartSec=210
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
"""
    timer = f"""[Unit]
Description=Optional scheduled Xray exit restart

[Timer]
OnCalendar={config["on_calendar"]}
AccuracySec=1s
Persistent=false
Unit={SERVICE}

[Install]
WantedBy=timers.target
"""
    atomic_write(unit_dir / SERVICE, service)
    atomic_write(unit_dir / TIMER, timer)
    checked(["systemd-analyze", "verify", str(unit_dir / SERVICE), str(unit_dir / TIMER)])
    checked(["systemctl", "daemon-reload"])
    if config["enabled"]:
        checked(["systemctl", "enable", TIMER])
        checked(["systemctl", "restart", TIMER])
    else:
        checked(["systemctl", "disable", "--now", TIMER])
    print(
        "Xray restart schedule "
        + ("enabled: " + config["on_calendar"] if config["enabled"] else "disabled")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "run", "apply"])
    parser.add_argument("--config", type=Path, default=Path("/etc/keyholder/xray-restart.json"))
    parser.add_argument("--unit-dir", type=Path, default=Path("/etc/systemd/system"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on the intended Xray host.")
    config = load_config(args.config)
    if args.action == "apply":
        apply(config, args.config.resolve(), args.unit_dir)
    else:
        restart(config, check_only=args.action == "check")


if __name__ == "__main__":
    main()
