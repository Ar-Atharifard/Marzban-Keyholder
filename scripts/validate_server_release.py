"""Validate an isolated on-server database clone; never run against a live volume."""

import asyncio
import base64
import hashlib
import http.client
import json
import os
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from keyholder.main import create_app
from keyholder.policies import SUPPORTED_KINDS
from keyholder.rendering.profiles import normalize
from keyholder.schemas import default_profiles


def receive(connection: socket.socket, size: int) -> bytes:
    result = b""
    while len(result) < size:
        block = connection.recv(size - len(result))
        if not block:
            raise ConnectionError("Incomplete SOCKS response")
        result += block
    return result


def check_connectivity(path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 18888))
    process = subprocess.Popen(
        ["/usr/local/bin/xray", "run", "-config", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _attempt in range(30):
            try:
                connection = socket.create_connection(("127.0.0.1", 18888), timeout=10)
                break
            except ConnectionRefusedError:
                assert process.poll() is None
                time.sleep(0.1)
        else:
            raise TimeoutError("Temporary client did not start")
        with connection:
            connection.sendall(b"\x05\x01\x00")
            assert receive(connection, 2) == b"\x05\x00"
            host = b"example.com"
            connection.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + b"\x01\xbb")
            response = receive(connection, 4)
            assert response[:2] == b"\x05\x00"
            size = {1: 4, 4: 16}.get(response[3])
            if response[3] == 3:
                size = receive(connection, 1)[0]
            assert size is not None
            receive(connection, size + 2)
            with ssl.create_default_context().wrap_socket(
                connection, server_hostname="example.com"
            ) as secure:
                secure.sendall(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n")
                result = http.client.HTTPResponse(secure)
                result.begin()
                assert result.status == 200
                assert result.read(65536), "Empty HTTPS body"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def validate() -> None:
    directory = Path("/data")
    assert (directory / ".release-rehearsal").read_text() == "isolated-clone\n"
    assert os.environ["KEYHOLDER_DATABASE_URL"] == "sqlite:////data/keyholder.db"
    database = directory / "keyholder.db"
    expected = list(SUPPORTED_KINDS) if "--pilot-expansion" in sys.argv else default_profiles()
    with closing(sqlite3.connect(database)) as db:
        before = db.execute("SELECT id,status,token_hash FROM customers ORDER BY id").fetchall()
        mappings = db.execute("SELECT * FROM customer_mappings ORDER BY customer_id").fetchall()
        policies = db.execute("SELECT id,policy FROM customers ORDER BY id").fetchall()
    result = subprocess.run(
        ["/app/.venv/bin/alembic", "upgrade", "head"], capture_output=True, timeout=30
    )
    assert result.returncode == 0
    with closing(sqlite3.connect(database)) as db:
        assert (
            db.execute("SELECT id,status,token_hash FROM customers ORDER BY id").fetchall()
            == before
        )
        assert (
            db.execute("SELECT * FROM customer_mappings ORDER BY customer_id").fetchall()
            == mappings
        )
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id,policy FROM customers ORDER BY id").fetchall() == policies
        row = db.execute("SELECT id FROM customers WHERE status='active' LIMIT 1").fetchone()
        assert row is not None
        # Only the clone receives a synthetic token. Live identities are untouched.
        token = secrets.token_urlsafe(32)
        db.execute(
            "UPDATE customers SET token_hash=?,policy=? WHERE id=?",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                json.dumps({"profiles": expected}),
                row[0],
            ),
        )
        db.commit()
    print("migration_clone_identity_mapping_status_and_integrity_ok", flush=True)
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://isolated-canary.test"
        ) as client:
            uri = await client.get("/s/" + token)
            xray = await client.get("/s/" + token + "?format=xray")
            assert uri.status_code == xray.status_code == 200
            links = base64.b64decode(uri.text, validate=True).decode().splitlines()
            profiles = [normalize(link) for link in links]
            assert len(profiles) == len(expected) and all(p is not None for p in profiles)
            assert {p.kind for p in profiles if p is not None} == set(expected)
            for link in links:
                query = parse_qs(urlsplit(link).query)
                if query.get("type") == ["xhttp"]:
                    assert "extra" not in query
            configs = xray.json()
            assert isinstance(configs, list) and len(configs) == len(expected)
            print("real_marzban_canary_both_formats_profiles_ok", len(expected), flush=True)
            path = directory / "xray-validation.json"
            try:
                for config in configs:
                    stream = config["outbounds"][0].get("streamSettings", {})
                    assert "extra" not in stream.get("xhttpSettings", {})
                    path.write_text(json.dumps(config))
                    path.chmod(0o600)
                    result = subprocess.run(
                        ["/usr/local/bin/xray", "run", "-test", "-config", str(path)],
                        capture_output=True,
                        timeout=15,
                    )
                    assert result.returncode == 0
                print("installed_xray_accepts_generated_configs", len(expected), flush=True)
                if "--connectivity" in sys.argv:
                    failed = False
                    for profile, config in zip(profiles, configs, strict=True):
                        assert profile is not None
                        config["inbounds"][0]["port"] = 18888
                        config["log"] = {"loglevel": "none"}
                        path.write_text(json.dumps(config))
                        try:
                            check_connectivity(path)
                            print(profile.kind, "https_connectivity_ok", flush=True)
                        except Exception as exc:
                            failed = True
                            print(
                                profile.kind, "connectivity_failed", type(exc).__name__, flush=True
                            )
                    assert not failed
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        asyncio.run(validate())
    except Exception as exc:
        # Exception messages may embed upstream URLs or customer configuration.
        print("server_release_validation_failed", type(exc).__name__)
        raise SystemExit(1) from None
