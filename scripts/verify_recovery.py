"""Verify a restored Marzban/Keyholder stack without printing customer data."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

API_CHECK = r"""
import base64, hashlib, json, sqlite3
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
from keyholder.config import Settings
s = Settings()
assert urlsplit(s.marzban_url).hostname in ('127.0.0.1', 'localhost', '::1')
opener = build_opener(ProxyHandler({}))
def request(path, admin=False):
    headers = {'Authorization': 'Bearer ' + s.admin_key.get_secret_value()} if admin else {}
    try:
        req = Request('http://127.0.0.1:18000' + path, headers=headers)
        with opener.open(req, timeout=20) as r:
            return r.status, r.read(1048577)
    except HTTPError as e:
        return e.code, b''
assert request('/health')[0] == 200
assert request('/admin/customers')[0] == 401
assert request('/s/invalid')[0] == 404
count = 0
candidate = None
with sqlite3.connect('file:/data/keyholder.db?mode=ro', uri=True) as db:
    rows = db.execute('SELECT id,status,token_hash,token_encrypted FROM customers').fetchall()
for identifier, status, digest, encrypted in rows:
    if not encrypted or status == 'revoked':
        continue
    vault = Fernet(s.token_encryption_key.get_secret_value().encode())
    token = vault.decrypt(encrypted.encode()).decode()
    assert hashlib.sha256(token.encode()).hexdigest() == digest
    code, body = request('/admin/customers/' + identifier + '/subscription', True)
    assert code == 200
    result = json.loads(body)
    assert result['token'] == token
    assert result['subscription_url'] == s.public_base_url.rstrip('/') + '/s/' + token
    count += 1
    if candidate is None and status == 'active':
        code, body = request('/s/' + token + '?format=uri')
        if code == 200:
            links = base64.b64decode(body, validate=True).decode().splitlines()
            assert links and all('://' in link for link in links)
            candidate = token
            profile_count = len(links)
assert candidate is not None, 'No active subscription available for rehearsal'
code, body = request('/s/' + candidate + '?format=xray')
assert code == 200 and isinstance(json.loads(body), list) and json.loads(body)
code, body = request('/s/' + candidate + '?format=info')
assert code == 200 and b'<html' in body.lower()
print(json.dumps({'retrievable_tokens':count, 'subscription_profiles':profile_count,
                  'uri_xray_info':True, 'private_admin':True}))
"""


def run(arguments: list[str], *, data: str | None = None, timeout: int = 60) -> str:
    result = subprocess.run(
        arguments, input=data, text=True, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise ValueError("Recovery check command failed; output withheld")
    return result.stdout


def database_rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database foreign key check failed")
        names = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {
            name: sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"'), key=repr)
            for (name,) in names
        }


def compare_database(original: Path, restored: Path) -> int:
    expected, actual = database_rows(original), database_rows(restored)
    if actual != expected:
        raise ValueError("Restored database differs from snapshot")
    return len(expected.get("customers", []))


def compare_panel(original: Path, restored: Path) -> int:
    expected, actual = database_rows(original), database_rows(restored)
    for name in ("proxies", "exclude_inbounds_association", "inbounds", "hosts"):
        if name in expected and expected[name] != actual.get(name):
            raise ValueError("Panel credentials or selections differ from snapshot")
    query = "SELECT id,username,data_limit,expire FROM users ORDER BY id"
    with sqlite3.connect(original.resolve().as_uri() + "?mode=ro", uri=True) as before:
        with sqlite3.connect(restored.resolve().as_uri() + "?mode=ro", uri=True) as after:
            users = before.execute(query).fetchall()
            if users != after.execute(query).fetchall():
                raise ValueError("Panel identity or plans differ from snapshot")
            if "admins" in expected:
                columns = [r[1] for r in before.execute("PRAGMA table_info(admins)")]
                stable = [name for name in columns if name != "users_usage"]
                fields = ",".join('"' + name.replace('"', '""') + '"' for name in stable)
                sql = "SELECT " + fields + " FROM admins ORDER BY id"
                if before.execute(sql).fetchall() != after.execute(sql).fetchall():
                    raise ValueError("Panel administrator credentials differ from snapshot")
                if "users_usage" in columns:
                    old_usage = dict(before.execute("SELECT id,users_usage FROM admins"))
                    new_usage = dict(after.execute("SELECT id,users_usage FROM admins"))
                    if any(new_usage[key] < used for key, used in old_usage.items()):
                        raise ValueError("Administrator usage counter decreased")
    return len(users)


def compare_core(original: Path, restored: Path) -> int:
    before, after = json.loads(original.read_text()), json.loads(restored.read_text())
    for config in (before, after):
        for inbound in config["inbounds"]:
            inbound.pop("listen", None)
    if before != after:
        raise ValueError("Core settings differ beyond rehearsal listener addresses")
    return len(before["inbounds"])


def proxy_checks(panel_db: Path, core_path: Path, binary: Path) -> dict[str, bool]:
    core = json.loads(core_path.read_text())
    inbound = next(
        i for i in core["inbounds"] if i.get("protocol") == "vless" and i.get("port") == 8443
    )
    if inbound["listen"] != "127.0.0.1":
        raise ValueError("Proxy rehearsal requires a loopback-only inbound")
    reality = inbound["streamSettings"]["realitySettings"]
    with sqlite3.connect(panel_db.resolve().as_uri() + "?mode=ro", uri=True) as db:
        candidates = db.execute(
            "SELECT p.settings FROM proxies p JOIN users u ON u.id=p.user_id "
            "WHERE u.status='active' AND lower(p.type)='vless' AND NOT EXISTS "
            "(SELECT 1 FROM exclude_inbounds_association e "
            "WHERE e.proxy_id=p.id AND e.inbound_tag=?)",
            (inbound["tag"],),
        ).fetchall()
    if not candidates:
        raise ValueError("No active VLESS account for proxy rehearsal")
    credential = json.loads(candidates[0][0])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="recovery-proxy-") as directory:
        path = Path(directory)
        config = {
            "log": {"loglevel": "none"},
            "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "http", "settings": {}}],
            "outbounds": [
                {
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": "127.0.0.1",
                                "port": 8443,
                                "users": [
                                    {
                                        "id": credential["id"],
                                        "encryption": "none",
                                        "flow": credential.get("flow", ""),
                                    }
                                ],
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "serverName": reality["serverNames"][0],
                            "publicKey": reality["publicKey"],
                            "shortId": reality["shortIds"][0],
                            "fingerprint": "chrome",
                        },
                    },
                }
            ],
        }
        client = path / "client.json"
        client.write_text(json.dumps(config))
        client.chmod(0o600)
        with (path / "client.log").open("wb") as log:
            process = subprocess.Popen(
                [str(binary), "run", "-config", str(client)],
                stdout=log,
                stderr=log,
                env={**os.environ, "XRAY_LOCATION_ASSET": str(binary.parent)},
            )
            try:
                for _ in range(50):
                    if process.poll() is not None:
                        raise ValueError("Temporary proxy failed to start")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise ValueError("Temporary proxy listener timed out")
                results = {}
                for name, url, allowed in (
                    ("foreign_https", "https://example.com/", True),
                    ("iranian_destination_blocked", "https://www.nic.ir/", False),
                    ("foreign_https_recheck", "https://example.com/", True),
                ):
                    response = subprocess.run(
                        [
                            "curl",
                            "--silent",
                            "--show-error",
                            "--proxy",
                            f"http://127.0.0.1:{port}",
                            "--noproxy",
                            "",
                            "--max-time",
                            "20",
                            "--output",
                            "/dev/null",
                            "--write-out",
                            "%{http_code}",
                            url,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=25,
                        check=False,
                    )
                    success = response.returncode == 0 and response.stdout in {
                        "200",
                        "204",
                        "301",
                        "302",
                    }
                    results[name] = success if allowed else not success
                if not all(results.values()):
                    raise ValueError("Proxy traffic or destination policy failed")
                return results
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    phase = "database"
    try:
        volume = json.loads(run(["docker", "volume", "inspect", "keyholder_keyholder-data"]))[0]
        count = compare_database(
            args.bundle / "volumes/keyholder_keyholder-data/keyholder.db",
            Path(volume["Mountpoint"]) / "keyholder.db",
        )
        phase = "panel identity, credentials and plans"
        upstream_count = compare_panel(
            args.bundle / "rootfs/var/lib/marzban/db.sqlite3",
            Path("/var/lib/marzban/db.sqlite3"),
        )
        phase = "core configuration"
        inbound_count = compare_core(
            args.bundle / "rootfs/var/lib/marzban/xray_config.json",
            Path("/var/lib/marzban/xray_config.json"),
        )
        phase = "api"
        api = json.loads(
            run(
                ["docker", "exec", "-i", "keyholder-api-1", "/app/.venv/bin/python", "-"],
                data=API_CHECK,
                timeout=180,
            )
        )
        phase = "operator CLI"
        run(["/usr/local/bin/keyholder", "--local", "system", "health"])
        phase = "gateway"
        run(["docker", "exec", "braavos-gateway", "nginx", "-t"])
        phase = "timer isolation"
        for unit in (
            "keyholder-management-bot.service",
            "keyholder-monitor.timer",
            "keyholder-recovery.timer",
            "keyholder-recovery-maintenance.timer",
        ):
            state = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
            if state.stdout.strip() in {"active", "activating", "reloading"}:
                raise ValueError("Duplicate bot or timer is running")
        phase = "proxy traffic"
        proxy = proxy_checks(
            Path("/var/lib/marzban/db.sqlite3"),
            Path("/var/lib/marzban/xray_config.json"),
            Path("/var/lib/marzban/xray-core/xray"),
        )
        report = {
            "passed": True,
            "customers_preserved": count,
            "upstream_users_preserved": upstream_count,
            "inbounds_preserved": inbound_count,
            "api": api,
            "proxy": proxy,
            "bots_and_timers_inactive": True,
        }
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        args.report.chmod(0o600)
        print(json.dumps(report))
    except (
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        sqlite3.Error,
        subprocess.SubprocessError,
    ):
        parser.exit(1, f"Recovery verification failed at {phase}; private output withheld.\n")


if __name__ == "__main__":
    main()
