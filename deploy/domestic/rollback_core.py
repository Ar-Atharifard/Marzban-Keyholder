"""Restore the saved Marzban core config if the domestic pilot is not confirmed."""

import shutil
import subprocess
from pathlib import Path

BACKUP = Path("/root/keyholder-domestic-core-before.json")
SOURCE = Path("/var/lib/marzban/xray_config.json")

UPDATE = """
import asyncio, json, sys, httpx
from keyholder.config import Settings
from keyholder.backends.marzban import MarzbanBackend

async def main():
    settings = Settings()
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as client:
        backend = MarzbanBackend(settings, client)
        await backend.login()
        response = await client.put(
            settings.marzban_url + '/api/core/config',
            headers={'Authorization': 'Bearer ' + backend.token},
            json=json.load(sys.stdin),
        )
        response.raise_for_status()

asyncio.run(main())
"""


def main() -> None:
    original = BACKUP.read_bytes()
    try:
        subprocess.run(
            ["docker", "exec", "-i", "keyholder-api-1", "/app/.venv/bin/python", "-c", UPDATE],
            input=original,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        shutil.copy2(BACKUP, SOURCE)
        subprocess.run(["docker", "restart", "marzban-marzban-1"], timeout=90, check=True)


if __name__ == "__main__":
    main()
