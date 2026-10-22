#!/usr/bin/python3
"""Check real TLS traffic through one loopback backhaul; never print credentials."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def healthy(port: int, account: dict[str, str]) -> bool:
    if port not in {19984, 19986, 19987}:
        raise ValueError("Unknown backhaul endpoint")
    if not account.get("user") or not account.get("pass"):
        raise ValueError("Missing backhaul authentication")
    credentials = "proxy-user = " + json.dumps(account["user"] + ":" + account["pass"]) + "\n"
    for url in ["https://1.1.1.1/cdn-cgi/trace", "https://www.gstatic.com/generate_204"]:
        try:
            result = subprocess.run(
                [
                    "/usr/bin/curl",
                    "-q",
                    "--config",
                    "-",
                    "--noproxy",
                    "",
                    "--proxy",
                    f"socks5h://127.0.0.1:{port}",
                    "--connect-timeout",
                    "2",
                    "--max-time",
                    "3",
                    "--max-filesize",
                    "4096",
                    "--silent",
                    "--output",
                    "/dev/null",
                    url,
                ],
                input=credentials,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            if result.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
    return False


def main() -> int:
    try:
        if len(sys.argv) != 5 or sys.argv[-2] != "127.0.0.1":
            return 1
        path = Path("/etc/keyholder-backhaul/probe.json")
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o007:
            return 1
        return 0 if healthy(int(sys.argv[-1]), json.loads(path.read_text())) else 1
    except (OSError, ValueError, KeyError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
