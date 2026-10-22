#!/usr/bin/python3
"""Map reviewed peer IPs in restored tunnel endpoints, without changing identities."""

import argparse
import ipaddress
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def address(value: str, mapping: dict[str, str]) -> str:
    if value in mapping:
        return mapping[value]
    for old, new in mapping.items():
        prefix = f"[{old}]:" if ":" in old else old + ":"
        if value.startswith(prefix):
            return (f"[{new}]:" if ":" in new else new + ":") + value[len(prefix) :]
    return value


def json_addresses(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [json_addresses(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: address(item, mapping)
            if key in {"address", "listen", "sendThrough"} and isinstance(item, str)
            else json_addresses(item, mapping)
            for key, item in value.items()
        }
    return value


def migrate(root: Path, mapping: dict[str, str], role: str) -> None:
    for old, new in mapping.items():
        if ipaddress.ip_address(old).version != ipaddress.ip_address(new).version:
            raise ValueError("Peer mapping must preserve address family")
    for name in ["server", "client"]:
        path = root / f"etc/keyholder-forward/{name}.json"
        if path.exists():
            data = json_addresses(json.loads(path.read_text()), mapping)
            path.write_text(json.dumps(data, indent=2) + "\n")
    for directory in ["keyholder-rathole", "keyholder-frp"]:
        for path in (root / "etc" / directory).glob("*.toml"):

            def replace(match: re.Match[str]) -> str:
                return match[1] + address(match[2], mapping) + match[3]

            pattern = (
                r'(?m)^(\s*(?:remote_addr|serverAddr|local_addr|bind_addr)\s*=\s*")([^"]+)(".*)$'
            )
            path.write_text(re.sub(pattern, replace, path.read_text()))
    if role == "domestic":
        path = root / "etc/haproxy/haproxy.cfg"
        text = path.read_text()
        for old, new in mapping.items():
            text = re.sub(r"(\bsrc\s+)" + re.escape(old) + r"(?=\s|\})", r"\g<1>" + new, text)
        path.write_text(text)
    else:
        path = root / "var/lib/marzban/db.sqlite3"
        if path.exists():
            with sqlite3.connect(path) as db:
                for old, new in mapping.items():
                    db.execute("UPDATE nodes SET address=? WHERE address=?", (new, old))
        path = root / "etc/keyholder/domestic-monitor.ssh"
        if path.exists():
            text = path.read_text()
            for old, new in mapping.items():
                text = re.sub(
                    r"(?mi)^(\s*HostName\s+)" + re.escape(old) + r"\s*$",
                    r"\g<1>" + new,
                    text,
                )
            path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--role", choices=["foreign", "domestic"], required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args()
    try:
        migrate(args.root, json.loads(args.mapping.read_text()), args.role)
    except (OSError, ValueError, sqlite3.Error):
        raise SystemExit("Peer mapping failed; inspect private restored endpoints.") from None
