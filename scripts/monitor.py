#!/usr/bin/env python3
"""Low-overhead host and Marzban monitoring with transition-based alerts.

This file intentionally uses only the Python standard library so it can run as a
short-lived systemd oneshot on small hosts.  Marzban remains the source of truth
for user status, quota, expiry and traffic counters.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

GIB = 1024**3


def utc_now() -> dt.datetime:
    # datetime.UTC is unavailable on the host's supported Python 3.10.
    return dt.datetime.now(dt.timezone.utc)  # noqa: UP017


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def private_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"{path} must not be a symlink")
    stat = path.stat()
    if os.geteuid() == 0 and (stat.st_uid != 0 or stat.st_mode & 0o077):
        raise ValueError(f"{path} must be root-owned and mode 0600")


def load_config(path: Path) -> dict[str, Any]:
    private_file(path)
    supplied = json.loads(path.read_text())
    if not isinstance(supplied, dict):
        raise ValueError("monitor configuration must be an object")
    defaults: dict[str, Any] = {
        "state_file": "/var/lib/keyholder-monitor/state.json",
        "secrets_file": "/etc/keyholder/monitor.env",
        "marzban_db": "/var/lib/marzban/db.sqlite3",
        "backup_dir": "/var/backups/keyholder",
        "containers": [],
        "systemd_units": [],
        "required_user_count": 1,
        "http_checks": [],
        "tcp_checks": [],
        "disk_warning_percent": 80,
        "disk_critical_percent": 90,
        "inode_warning_percent": 85,
        "inode_critical_percent": 95,
        "memory_available_warning_mib": 120,
        "swap_warning_percent": 75,
        "load_warning_per_cpu": 1.5,
        "backup_max_age_hours": 26,
        "expiry_warning_days": [7, 3, 1],
        "quota_warning_percent": [80, 95],
        "terminal_reminder_hours": 24,
        "terminal_silence_hours": 72,
        "traffic_min_gib": 1,
        "traffic_rate_gib_per_hour": 20,
        "traffic_baseline_multiplier": 3,
    }
    unknown = supplied.keys() - defaults.keys()
    if unknown:
        raise ValueError("unknown monitor configuration fields: " + ", ".join(sorted(unknown)))
    defaults.update(supplied)
    return defaults


def read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0]) * 1024
    return values


def container_alerts(items: list[dict[str, Any]]) -> dict[str, str]:
    alerts: dict[str, str] = {}
    for item in items:
        name = str(item["name"])
        result = subprocess.run(
            ["docker", "inspect", name], capture_output=True, timeout=10, check=False
        )
        if result.returncode:
            alerts[f"container:{name}"] = f"Container {name} cannot be inspected"
            continue
        state = json.loads(result.stdout)[0]["State"]
        if not state.get("Running"):
            alerts[f"container:{name}"] = f"Container {name} is not running"
            continue
        health = (state.get("Health") or {}).get("Status")
        if item.get("require_health") and health != "healthy":
            alerts[f"container:{name}"] = f"Container {name} health is {health or 'missing'}"
    return alerts


def systemd_alerts(units: list[str]) -> dict[str, str]:
    alerts: dict[str, str] = {}
    for unit in units:
        result = subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, timeout=5, check=False
        )
        state = result.stdout.decode(errors="replace").strip() or "unknown"
        if result.returncode or state != "active":
            alerts[f"systemd:{unit}"] = f"Systemd unit {unit} is {state}"
    return alerts


def system_metrics() -> dict[str, Any]:
    memory = read_meminfo()
    disk = shutil.disk_usage("/")
    fs = os.statvfs("/")
    cpu = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    network = {"received_bytes": 0, "sent_bytes": 0}
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        interface, values = line.split(":", 1)
        if interface.strip() == "lo" or interface.strip().startswith(("veth", "docker", "br-")):
            continue
        fields = values.split()
        network["received_bytes"] += int(fields[0])
        network["sent_bytes"] += int(fields[8])
    return {
        "memory_total_mib": round(memory.get("MemTotal", 0) / 1024**2, 1),
        "memory_available_mib": round(memory.get("MemAvailable", 0) / 1024**2, 1),
        "swap_used_mib": round(
            (memory.get("SwapTotal", 0) - memory.get("SwapFree", 0)) / 1024**2, 1
        ),
        "swap_total_mib": round(memory.get("SwapTotal", 0) / 1024**2, 1),
        "disk_used_gib": round(disk.used / GIB, 2),
        "disk_total_gib": round(disk.total / GIB, 2),
        "disk_free_gib": round(disk.free / GIB, 2),
        "inode_used_percent": round(100 * (fs.f_files - fs.f_ffree) / fs.f_files, 1)
        if fs.f_files
        else None,
        "cpus": os.cpu_count() or 1,
        "load_1_5_15": list(os.getloadavg()),
        "uptime_seconds": int(float(Path("/proc/uptime").read_text().split()[0])),
        "cpu_total_ticks": sum(cpu),
        "cpu_idle_ticks": cpu[3] + cpu[4],
        **network,
    }


def resource_alerts(config: dict[str, Any]) -> dict[str, str]:
    alerts: dict[str, str] = {}
    disk = shutil.disk_usage("/")
    disk_percent = 100 * disk.used / disk.total
    if disk_percent >= float(config["disk_critical_percent"]):
        alerts["disk:critical"] = f"Root disk is {disk_percent:.1f}% full"
    elif disk_percent >= float(config["disk_warning_percent"]):
        alerts["disk:warning"] = f"Root disk is {disk_percent:.1f}% full"

    filesystem = os.statvfs("/")
    if filesystem.f_files:
        inode_percent = 100 * (filesystem.f_files - filesystem.f_ffree) / filesystem.f_files
        if inode_percent >= float(config["inode_critical_percent"]):
            alerts["inode:critical"] = f"Root filesystem inodes are {inode_percent:.1f}% used"
        elif inode_percent >= float(config["inode_warning_percent"]):
            alerts["inode:warning"] = f"Root filesystem inodes are {inode_percent:.1f}% used"

    memory = read_meminfo()
    available_mib = memory.get("MemAvailable", 0) / 1024**2
    if available_mib < float(config["memory_available_warning_mib"]):
        alerts["memory:available"] = f"Available memory is {available_mib:.0f} MiB"
    swap_total = memory.get("SwapTotal", 0)
    if swap_total:
        swap_percent = 100 * (swap_total - memory.get("SwapFree", 0)) / swap_total
        if swap_percent >= float(config["swap_warning_percent"]):
            alerts["swap:used"] = f"Swap usage is {swap_percent:.1f}%"

    cpu_count = os.cpu_count() or 1
    load = os.getloadavg()[0]
    if load >= float(config["load_warning_per_cpu"]) * cpu_count:
        alerts["cpu:load"] = f"One-minute load is {load:.2f} across {cpu_count} CPUs"
    return alerts


def network_alerts(config: dict[str, Any]) -> dict[str, str]:
    alerts: dict[str, str] = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for item in config["http_checks"]:
        name = str(item["name"])
        request = urllib.request.Request(
            str(item["url"]), headers={"User-Agent": "keyholder-monitor/1"}
        )
        try:
            with opener.open(request, timeout=float(item.get("timeout", 8))) as response:
                expected = int(item.get("status", 200))
                if response.status != expected:
                    raise ValueError(f"HTTP {response.status}, expected {expected}")
                marker = item.get("contains")
                if marker and str(marker).encode() not in response.read(65536):
                    raise ValueError("expected response marker is missing")
        except Exception as error:
            alerts[f"http:{name}"] = f"HTTP check {name} failed: {type(error).__name__}"
    for item in config["tcp_checks"]:
        name = str(item["name"])
        try:
            with socket.create_connection(
                (str(item["host"]), int(item["port"])), float(item.get("timeout", 3))
            ):
                pass
        except OSError:
            alerts[f"tcp:{name}"] = f"TCP check {name} failed"
    return alerts


def backup_alerts(config: dict[str, Any], now: float) -> dict[str, str]:
    folder = Path(config["backup_dir"])
    try:
        newest = max((path.stat().st_mtime for path in folder.iterdir()), default=0)
    except OSError:
        newest = 0
    age_hours = (now - newest) / 3600 if newest else float("inf")
    if age_hours > float(config["backup_max_age_hours"]):
        age = "missing" if newest == 0 else f"{age_hours:.1f} hours old"
        return {"backup:age": f"Latest recovery snapshot is {age}"}
    return {}


def baseline_by_user(db: sqlite3.Connection, current_hour: str) -> dict[int, float]:
    rows = db.execute(
        """
        SELECT user_id, AVG(used_traffic) FROM node_user_usages
        WHERE created_at >= datetime('now', '-7 days') AND created_at < ?
          AND used_traffic > 0
        GROUP BY user_id
        """,
        (current_hour,),
    )
    return {int(user_id): float(value) for user_id, value in rows}


def user_alerts(
    config: dict[str, Any], previous: dict[str, Any], now: dt.datetime
) -> tuple[dict[str, str], dict[str, int]]:
    path = Path(config["marzban_db"])
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    current_hour = now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    baseline = baseline_by_user(db, current_hour)
    rows = db.execute(
        "SELECT id,username,status,used_traffic,data_limit,expire FROM users ORDER BY id"
    ).fetchall()
    alerts: dict[str, str] = {}
    if len(rows) < int(config["required_user_count"]):
        alerts["marzban:users"] = (
            f"Marzban has {len(rows)} users; expected at least {config['required_user_count']}"
        )
    counters: dict[str, int] = {}
    old_counters = previous.get("user_counters", {})
    old_time = float(previous.get("sampled_at", now.timestamp()))
    elapsed = max(now.timestamp() - old_time, 1)
    for row in rows:
        user_id = str(row["id"])
        username = str(row["username"])
        used = int(row["used_traffic"] or 0)
        counters[user_id] = used
        limit = int(row["data_limit"] or 0)
        expire = int(row["expire"] or 0)
        reasons = []
        if limit and used >= limit:
            reasons.append("quota exhausted")
        if expire and expire <= now.timestamp():
            reasons.append("expired")
        if str(row["status"]) in {"limited", "expired"} and not reasons:
            reasons.append(str(row["status"]))
        if reasons:
            alerts[f"user:{user_id}:account"] = f"User {username}: {', '.join(reasons)}"
            continue
        if str(row["status"]) not in {"active", "on_hold"}:
            alerts[f"user:{user_id}:status"] = f"User {username} status is {row['status']}"
        limit = int(row["data_limit"] or 0)
        if limit > 0:
            percent = 100 * used / limit
            crossed = [int(x) for x in config["quota_warning_percent"] if percent >= float(x)]
            if crossed:
                threshold = max(crossed)
                alerts[f"user:{user_id}:quota"] = (
                    f"User {username} has used {percent:.1f}% of quota (threshold {threshold}%)"
                )
        expire = int(row["expire"] or 0)
        if expire > 0:
            days = (expire - now.timestamp()) / 86400
            crossed_days = [int(x) for x in config["expiry_warning_days"] if days <= float(x)]
            if crossed_days:
                threshold = min(crossed_days)
                alerts[f"user:{user_id}:expiry"] = (
                    f"User {username} expires in {max(days, 0):.1f} days "
                    f"(threshold {threshold} days)"
                )
        old = int(old_counters.get(user_id, used))
        delta = max(used - old, 0)
        rate = delta * 3600 / elapsed
        historical = baseline.get(int(row["id"]), 0)
        if (
            delta >= float(config["traffic_min_gib"]) * GIB
            and rate >= float(config["traffic_rate_gib_per_hour"]) * GIB
            and (
                historical == 0 or rate >= historical * float(config["traffic_baseline_multiplier"])
            )
        ):
            alerts[f"user:{user_id}:traffic"] = (
                f"User {username} traffic rate is approximately {rate / GIB:.1f} GiB/hour"
            )
    db.close()
    return alerts, counters


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    handle, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as file:
            json.dump(state, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def telegram(env: dict[str, str], text: str) -> bool:
    token = env.get("KEYHOLDER_ALERT_BOT_TOKEN")
    chat = env.get("KEYHOLDER_ALERT_CHAT_ID")
    if not token or not chat:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for offset in range(0, len(text), 3500):
        body = urllib.parse.urlencode(
            {
                "chat_id": chat,
                "text": text[offset : offset + 3500],
                "disable_web_page_preview": "true",
            }
        ).encode()
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=body, method="POST"
        )
        with opener.open(request, timeout=10) as response:
            if not json.load(response).get("ok"):
                raise ValueError("Telegram rejected alert delivery")

    return True


def heartbeat(env: dict[str, str]) -> None:
    url = env.get("KEYHOLDER_HEARTBEAT_URL")
    if not url:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "keyholder-monitor/1"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10):
        pass


def summarize(prefix: str, alerts: dict[str, str]) -> str:
    lines = [f"{prefix} on Braavos"]
    lines.extend(f"• {message}" for _, message in sorted(alerts.items()))
    return "\n".join(lines)


def infrastructure_healthy(alerts: dict[str, str]) -> bool:
    return not any(not key.startswith("user:") for key in alerts)


def notification_signature(key: str, message: str) -> str:
    """Suppress changing measurements while retaining meaningful severity changes."""
    if key.endswith(":quota"):
        match = re.search(r"threshold ([0-9]+)%", message)
        return f"{key}:{match.group(1)}" if match else key
    if key.endswith(":expiry"):
        match = re.search(r"threshold ([0-9]+) days", message)
        return f"{key}:{match.group(1)}" if match else key
    if key.endswith(":status") or key.startswith(("container:", "systemd:")):
        return f"{key}:{message}"
    return key


def terminal_notifications(
    alerts: dict[str, str], previous: dict[str, Any], now: float, config: dict[str, Any]
) -> tuple[dict[str, Any], set[str], set[str]]:
    tracking = {}
    reminders: set[str] = set()
    silenced: set[str] = set()
    for key in alerts:
        if not key.endswith(":account"):
            continue
        old = previous.get("terminal_accounts", {}).get(key, {})
        entry = {"since": float(old.get("since", now)), "last_sent": float(old.get("last_sent", 0))}
        tracking[key] = entry
        if now - entry["since"] >= float(config["terminal_silence_hours"]) * 3600:
            silenced.add(key)
        elif (
            entry["last_sent"]
            and now - entry["last_sent"] >= float(config["terminal_reminder_hours"]) * 3600
        ):
            reminders.add(key)
    return tracking, reminders, silenced


def run(config: dict[str, Any], notify: bool = True) -> dict[str, Any]:
    state_path = Path(config["state_file"])
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return run_locked(config, notify)


def run_locked(config: dict[str, Any], notify: bool = True) -> dict[str, Any]:
    now = utc_now()
    state_path = Path(config["state_file"])
    previous = load_state(state_path)
    alerts: dict[str, str] = {}
    alerts.update(container_alerts(config["containers"]))
    alerts.update(systemd_alerts(config["systemd_units"]))
    alerts.update(resource_alerts(config))
    alerts.update(network_alerts(config))
    alerts.update(backup_alerts(config, now.timestamp()))
    try:
        per_user, counters = user_alerts(config, previous, now)
        alerts.update(per_user)
    except (OSError, sqlite3.Error, ValueError):
        alerts["marzban:usage"] = "Marzban usage database could not be inspected"
        counters = previous.get("user_counters", {})

    terminal, reminders, silenced = terminal_notifications(
        alerts, previous, now.timestamp(), config
    )
    notified_alerts = previous.get("notified_alerts", {})
    new = {
        key: value
        for key, value in alerts.items()
        if key not in silenced
        and (
            key in reminders
            or key not in notified_alerts
            or notification_signature(key, value)
            != notification_signature(key, str(notified_alerts[key]))
        )
    }
    recovered = {key: value for key, value in notified_alerts.items() if key not in alerts}
    env_path = Path(config["secrets_file"])
    env = parse_env(env_path)
    if env_path.exists():
        private_file(env_path)
    delivery_error = None
    delivered_alerts = dict(notified_alerts)
    if notify:
        try:
            sections = []
            if new:
                sections.append(summarize("ALERT", new))
            if recovered:
                sections.append(summarize("RECOVERED", recovered))
            if sections and telegram(env, "\n\n".join(sections)):
                delivered_alerts.update(new)
                for key in recovered:
                    delivered_alerts.pop(key, None)
                for key in new.keys() & terminal.keys():
                    terminal[key]["last_sent"] = now.timestamp()
            # Business warnings (quota, expiry, account status and traffic) must not
            # suppress the infrastructure heartbeat. Otherwise Better Stack reports
            # the whole VPS down when one customer merely approaches a quota.
            if infrastructure_healthy(alerts):
                heartbeat(env)
        except Exception as error:
            delivery_error = type(error).__name__

    metrics = system_metrics()
    old_metrics = previous.get("metrics", {})
    total_delta = metrics["cpu_total_ticks"] - old_metrics.get(
        "cpu_total_ticks", metrics["cpu_total_ticks"]
    )
    idle_delta = metrics["cpu_idle_ticks"] - old_metrics.get(
        "cpu_idle_ticks", metrics["cpu_idle_ticks"]
    )
    metrics["cpu_busy_percent"] = (
        round(max(0, min(100, 100 * (1 - idle_delta / total_delta))), 1)
        if total_delta > 0
        else None
    )
    result = {
        "metrics": metrics,
        "terminal_accounts": terminal,
        "silenced_alerts": sorted(silenced),
        "healthy": not alerts,
        "checked_at": now.isoformat(),
        "alert_count": len(alerts),
        "alerts": alerts,
        "notified_alerts": delivered_alerts,
        "new_alerts": sorted(new),
        "recovered_alerts": sorted(recovered),
        "notification_error": delivery_error,
        "sampled_at": now.timestamp(),
        "user_counters": counters,
    }
    save_state(state_path, result)
    return result


def public_result(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "healthy": bool(state.get("healthy")),
        "checked_at": state.get("checked_at"),
        "alert_count": int(state.get("alert_count", 0)),
        "alerts": state.get("alerts", {}),
        "notification_error": state.get("notification_error"),
        "metrics": state.get("metrics", {}),
        "silenced_alerts": state.get("silenced_alerts", []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/keyholder/monitor.json"))
    parser.add_argument(
        "--metrics", action="store_true", help="Read live system metrics without a check"
    )
    parser.add_argument("--status", action="store_true", help="Read the last result only")
    parser.add_argument("--no-notify", action="store_true", help="Run checks without notifications")
    parser.add_argument("--test-alert", action="store_true", help="Send one Telegram test alert")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.metrics:
            metrics = system_metrics()
            previous = load_state(Path(config["state_file"]))
            metrics["cpu_busy_percent"] = previous.get("metrics", {}).get("cpu_busy_percent")
            metrics["cpu_sampled_at"] = previous.get("checked_at")
            print(json.dumps(metrics))
            return 0
        if args.test_alert:
            env_path = Path(config["secrets_file"])
            private_file(env_path)
            if not telegram(parse_env(env_path), "TEST ALERT from Braavos monitoring"):
                raise ValueError("Telegram alerting is not configured")
            print(json.dumps({"healthy": True, "telegram": "delivered"}))
            return 0
        state = (
            load_state(Path(config["state_file"]))
            if args.status
            else run(config, notify=not args.no_notify)
        )
        print(json.dumps(public_result(state), ensure_ascii=False))
        return 0 if state.get("healthy") else 1
    except Exception:
        print(json.dumps({"healthy": False, "error": "monitor execution failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
