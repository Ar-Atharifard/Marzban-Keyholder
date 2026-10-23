#!/usr/bin/python3
"""Check real TLS traffic through one loopback backhaul; never print credentials."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


OPTIONS = component_settings(
    "backhaul_probe",
    {
        "ports": [19984, 19986, 19987],
        "urls": ["https://1.1.1.1/cdn-cgi/trace", "https://www.gstatic.com/generate_204"],
        "credentials_file": "/etc/keyholder-backhaul/probe.json",
        "curl_binary": "/usr/bin/curl",
        "connect_timeout_seconds": 2,
        "request_timeout_seconds": 3,
        "process_timeout_seconds": 4,
        "max_response_bytes": 4096,
    },
)


def healthy(port: int, account: dict[str, str]) -> bool:
    if port not in OPTIONS["ports"]:
        raise ValueError("Unknown backhaul endpoint")
    if not account.get("user") or not account.get("pass"):
        raise ValueError("Missing backhaul authentication")
    credentials = "proxy-user = " + json.dumps(account["user"] + ":" + account["pass"]) + "\n"
    for url in OPTIONS["urls"]:
        try:
            result = subprocess.run(
                [
                    OPTIONS["curl_binary"],
                    "-q",
                    "--config",
                    "-",
                    "--noproxy",
                    "",
                    "--proxy",
                    f"socks5h://127.0.0.1:{port}",
                    "--connect-timeout",
                    str(OPTIONS["connect_timeout_seconds"]),
                    "--max-time",
                    str(OPTIONS["request_timeout_seconds"]),
                    "--max-filesize",
                    str(OPTIONS["max_response_bytes"]),
                    "--silent",
                    "--output",
                    "/dev/null",
                    url,
                ],
                input=credentials,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=OPTIONS["process_timeout_seconds"],
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
        path = Path(OPTIONS["credentials_file"])
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o007:
            return 1
        return 0 if healthy(int(sys.argv[-1]), json.loads(path.read_text())) else 1
    except (OSError, ValueError, KeyError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
