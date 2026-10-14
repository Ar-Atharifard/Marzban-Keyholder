"""Root-owned SSH dispatcher; credentials stay inside the API container."""

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
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
        "management_bot_env": "/etc/keyholder/management-bot.env",
        "management_bot_service": "keyholder-management-bot.service",
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


def discover_chat_id(token: str) -> str:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates",
        headers={"User-Agent": "keyholder-alert-setup/1"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=15) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise ValueError("Telegram rejected the bot token")
    chats: dict[str, None] = {}
    for update in payload.get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private" and isinstance(chat.get("id"), int):
            chats[str(chat["id"])] = None
    if len(chats) != 1:
        raise ValueError("Send /start to the new bot from exactly one private account")
    return next(iter(chats))


def configure_alerts(config: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    token = str(args.get("bot_token", ""))
    chat_id = str(args.get("chat_id", ""))
    if not re.fullmatch(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}", token):
        raise ValueError("Invalid Telegram bot token")
    if not chat_id:
        chat_id = discover_chat_id(token)
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


def write_monitor_env(config: dict[str, Any], changes: dict[str, str]) -> None:
    monitor_config = Path(config["monitor_config"])
    settings = json.loads(monitor_config.read_text())
    destination = Path(settings["secrets_file"])
    current: dict[str, str] = {}
    if destination.exists():
        for line in destination.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                current[key] = value
    current.update(changes)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".monitor-env-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            for key in (
                "KEYHOLDER_ALERT_BOT_TOKEN",
                "KEYHOLDER_ALERT_CHAT_ID",
                "KEYHOLDER_HEARTBEAT_URL",
            ):
                file.write(f"{key}={current.get(key, '')}\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def heartbeat_url(config: dict[str, Any]) -> str:
    settings = json.loads(Path(config["monitor_config"]).read_text())
    destination = Path(settings["secrets_file"])
    if destination.exists():
        for line in destination.read_text().splitlines():
            if line.startswith("KEYHOLDER_HEARTBEAT_URL="):
                return line.split("=", 1)[1]
    return ""


def validate_heartbeat_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or len(value) > 2048
    ):
        raise ValueError("Invalid HTTPS heartbeat URL")
    return value


def configure_management_bot(config: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    token = str(args.get("bot_token", ""))
    chat_id = str(args.get("chat_id", ""))
    if not re.fullmatch(r"[0-9]{6,15}:[A-Za-z0-9_-]{30,100}", token):
        raise ValueError("Invalid Telegram bot token")
    if not chat_id:
        chat_id = discover_chat_id(token)
    if not re.fullmatch(r"[0-9]{5,20}", chat_id):
        raise ValueError("Management bot requires one private Telegram account")
    destination = Path(config["management_bot_env"])
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".management-bot-env-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(f"KEYHOLDER_MANAGEMENT_BOT_TOKEN={token}\n")
            file.write(f"KEYHOLDER_MANAGEMENT_ADMIN_ID={chat_id}\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    subprocess.run(
        ["systemctl", "enable", "--now", config["management_bot_service"]],
        capture_output=True,
        timeout=20,
        check=True,
    )
    return {"configured": True, "administrator_id": chat_id}


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
    if operation == "heartbeat-configure":
        url = validate_heartbeat_url(str(payload.get("args", {}).get("heartbeat_url", "")))
        write_monitor_env(config, {"KEYHOLDER_HEARTBEAT_URL": url})
        return {"ok": True, "result": {"configured": True}}
    if operation == "heartbeat-test":
        url = heartbeat_url(config)
        if not url:
            raise ValueError("Heartbeat is not configured")
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            urllib.request.Request(url, headers={"User-Agent": "keyholder-monitor/1"}), timeout=15
        ):
            pass
        return {"ok": True, "result": {"delivered": True}}
    if operation == "management-bot-configure":
        return {
            "ok": True,
            "result": configure_management_bot(config, payload.get("args", {})),
        }
    if operation == "management-bot-status":
        result = subprocess.run(
            ["systemctl", "is-active", config["management_bot_service"]],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return {
            "ok": True,
            "result": {
                "configured": Path(config["management_bot_env"]).exists(),
                "active": result.stdout.decode().strip() == "active",
            },
        }
    if operation == "management-bot-test":
        env: dict[str, str] = {}
        for line in Path(config["management_bot_env"]).read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                env[key] = value
        body = urllib.parse.urlencode(
            {
                "chat_id": env["KEYHOLDER_MANAGEMENT_ADMIN_ID"],
                "text": "Keyholder management bot is ready.",
            }
        ).encode()
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            urllib.request.Request(
                "https://api.telegram.org/bot"
                + env["KEYHOLDER_MANAGEMENT_BOT_TOKEN"]
                + "/sendMessage",
                data=body,
                method="POST",
            ),
            timeout=15,
        ):
            pass
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
