"""Root-owned SSH dispatcher; credentials stay inside the API container."""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTAINER = "keyholder-api-1"


def inspect(name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, timeout=10, check=True
    )
    return json.loads(result.stdout)[0]  # type: ignore[no-any-return]


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload["operation"]
    if operation == "status":
        states = []
        for name in [CONTAINER, "braavos-gateway", "marzban-marzban-1"]:
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
        state = json.loads(Path("/opt/braavos-panel/access.json").read_text())
        return {"ok": True, "result": {"panel_url": state["panel_url"], "active": state["active"]}}
    if operation == "backup":
        item = inspect(CONTAINER)
        source = next(
            Path(m["Source"]) / "keyholder.db"
            for m in item["Mounts"]
            if m["Destination"] == "/data" and m["Type"] == "volume"
        )
        folder = Path("/var/backups/keyholder")
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
        shutil.copy2("/srv/keyholder/.env", recovery / "keyholder.env")
        (recovery / "keyholder.env").chmod(0o600)
        subprocess.run(
            [
                sys.executable,
                str(tool),
                "--source",
                "/var/lib/marzban/db.sqlite3",
                "--destination",
                str(recovery / "marzban.sqlite3"),
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
                "includes": ["keyholder", "vault-key-env", "marzban"],
            },
        }
    worker = Path(__file__).with_name("worker.py").read_text()
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "/app/.venv/bin/python", "-c", worker],
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
