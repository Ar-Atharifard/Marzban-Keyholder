"""Root-owned SSH dispatcher; credentials stay inside the API container."""

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def configuration() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "api_container": "keyholder-api-1",
        "status_containers": ["keyholder-api-1"],
        "container_python": "/app/.venv/bin/python",
        "api_url": "http://127.0.0.1:18000",
        "panel_access_file": "/etc/keyholder/panel-access.json",
        "backup_dir": "/var/backups/keyholder",
        "env_file": "/etc/keyholder/keyholder.env",
        "extra_backups": {},
        "sqlite_backups": {},
        "monitor_tool": "/usr/local/lib/keyholder-admin/monitor.py",
        "monitor_config": "/etc/keyholder/monitor.json",
    }
    file = Path(os.getenv("KEYHOLDER_HOST_CONFIG", str(Path(__file__).with_name("host.json"))))
    if file.exists():
        if file.is_symlink() or file.stat().st_uid != 0 or file.stat().st_mode & 0o077:
            raise ValueError("Host configuration must be root-owned and private")
        supplied = json.loads(file.read_text())
        if not isinstance(supplied, dict) or not supplied.keys() <= defaults.keys():
            raise ValueError("Unknown host configuration field")
        defaults.update(supplied)
    return defaults


def inspect(name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, timeout=10, check=True
    )
    return json.loads(result.stdout)[0]  # type: ignore[no-any-return]


def configure_alerts(config: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    token = str(args.get("bot_token", ""))
    chat_id = str(args.get("chat_id", ""))
    if not re.fullmatch(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}", token):
        raise ValueError("Invalid Telegram bot token")
    if not re.fullmatch(r"-?[0-9]{5,20}", chat_id):
        raise ValueError("Invalid Telegram chat ID")
    monitor_config = Path(config["monitor_config"])
    settings = json.loads(monitor_config.read_text())
    destination = Path(settings["secrets_file"])
    heartbeat = ""
    if destination.exists():
        for line in destination.read_text().splitlines():
            if line.startswith("KEYHOLDER_HEARTBEAT_URL="):
                heartbeat = line.split("=", 1)[1]
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".monitor-env-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(f"KEYHOLDER_ALERT_BOT_TOKEN={token}\n")
            file.write(f"KEYHOLDER_ALERT_CHAT_ID={chat_id}\n")
            file.write(f"KEYHOLDER_HEARTBEAT_URL={heartbeat}\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"configured": True, "chat_id": chat_id}


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    config = configuration()
    container = str(config["api_container"])
    operation = payload["operation"]
    if operation == "status":
        states = []
        for name in config["status_containers"]:
            item = inspect(name)
            states.append(
                {
                    "container": name,
                    "running": item["State"]["Running"],
                    "health": item["State"].get("Health", {}).get("Status"),
                    "image": item["Image"],
                }
            )
        return {"ok": True, "result": states}
    if operation == "panel-url":
        state = json.loads(Path(config["panel_access_file"]).read_text())
        return {"ok": True, "result": {"panel_url": state["panel_url"], "active": state["active"]}}
    if operation in {"monitor-status", "monitor-run"}:
        command = [
            sys.executable,
            str(config["monitor_tool"]),
            "--config",
            str(config["monitor_config"]),
        ]
        if operation == "monitor-status":
            command.append("--status")
        else:
            command.append("--no-notify")
        result = subprocess.run(command, capture_output=True, timeout=50, check=False)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            raise ValueError("Monitor returned invalid output") from None
        return {"ok": True, "result": report}
    if operation == "alerts-configure":
        return {"ok": True, "result": configure_alerts(config, payload.get("args", {}))}
    if operation == "alerts-test":
        result = subprocess.run(
            [
                sys.executable,
                str(config["monitor_tool"]),
                "--config",
                str(config["monitor_config"]),
                "--test-alert",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise ValueError("Telegram test delivery failed")
        return {"ok": True, "result": {"delivered": True}}
    if operation == "backup":
        item = inspect(container)
        source = next(
            Path(m["Source"]) / "keyholder.db"
            for m in item["Mounts"]
            if m["Destination"] == "/data" and m["Type"] == "volume"
        )
        folder = Path(config["backup_dir"])
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink() or folder.stat().st_uid != 0 or folder.stat().st_mode & 0o077:
            raise ValueError("Backup directory must be root-only")
        destination = folder / (
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")  # noqa: UP017
            + ".sqlite3"
        )
        tool = Path(__file__).with_name("backup_database.py")
        subprocess.run(
            [sys.executable, str(tool), "--source", str(source), "--destination", str(destination)],
            capture_output=True,
            timeout=40,
            check=True,
        )
        # The encrypted vault needs its server-only key; keep it with a root-only recovery set.
        import shutil

        recovery = folder / destination.stem
        recovery.mkdir(mode=0o700)
        shutil.copy2(destination, recovery / "keyholder.sqlite3")
        shutil.copy2(config["env_file"], recovery / "keyholder.env")
        (recovery / "keyholder.env").chmod(0o600)
        for name, backup_source in config["extra_backups"].items():
            if Path(name).name != name or name in {"keyholder.env", "keyholder.sqlite3"}:
                raise ValueError("Invalid backup destination")
            shutil.copy2(backup_source, recovery / name)
            (recovery / name).chmod(0o600)
        for name, source in config["sqlite_backups"].items():
            if Path(name).name != name or name in {"keyholder.env", "keyholder.sqlite3"}:
                raise ValueError("Invalid SQLite backup destination")
            subprocess.run(
                [
                    sys.executable,
                    str(tool),
                    "--source",
                    str(source),
                    "--destination",
                    str(recovery / name),
                ],
                capture_output=True,
                timeout=40,
                check=True,
            )
        return {
            "ok": True,
            "result": {
                "backup": str(recovery),
                "integrity": "ok",
                "includes": [
                    "keyholder",
                    "vault-key-env",
                    *config["extra_backups"],
                    *config["sqlite_backups"],
                ],
            },
        }
    worker = Path(__file__).with_name("worker.py").read_text()
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "KEYHOLDER_OPERATOR_API_URL=" + config["api_url"],
            container,
            config["container_python"],
            "-c",
            worker,
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=60,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def main() -> None:
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("Request too large")
        print(json.dumps(execute(json.loads(raw))))
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "Server operation failed; private diagnostics withheld."}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
