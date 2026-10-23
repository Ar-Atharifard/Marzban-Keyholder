#!/usr/bin/env python3
"""Test authenticated subscription profiles from the server without logging credentials."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

EXPORT = """
import asyncio, inspect, sys, httpx
from keyholder.config import Settings
from keyholder.backends.marzban import MarzbanBackend
from keyholder.rendering.profiles import normalize
from keyholder.rendering.renderers import XrayRenderer
async def main():
    settings = Settings()
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        backend = MarzbanBackend(settings, client)
        data = await backend.subscription_details(sys.argv[1])
        if data.status != 'active':
            raise ValueError('Monitoring account is inactive')
        networks = getattr(settings, 'allowed_cdn_networks', ())
        profiles = []
        for link in data.links:
            if len(inspect.signature(normalize).parameters) > 1:
                profile = normalize(link, networks)
            else:
                profile = normalize(link)
            if profile is not None:
                profiles.append(profile)
        print(XrayRenderer().render(profiles))
asyncio.run(main())
"""


if TYPE_CHECKING or __package__:
    from scripts.component_config import settings as component_settings
else:
    from component_config import settings as component_settings


OPTIONS = component_settings(
    "proxy_probe",
    {
        "urls": ["https://www.gstatic.com/generate_204", "https://example.com/"],
        "foreign_urls": [
            "https://www.youtube.com/generate_204",
            "https://www.facebook.com/robots.txt",
        ],
        "domestic_urls": ["https://www.aparat.com/", "https://www.digikala.com/"],
        "dns_address": "1.1.1.1",
        "dns_port": 53,
        "dns_query_name": "example.com",
        "connect_timeout_seconds": 2,
        "request_timeout_seconds": 4,
        "process_timeout_seconds": 6,
        "udp_timeout_seconds": 4,
        "workers": 4,
        "startup_attempts": 40,
        "startup_interval_seconds": 0.1,
        "max_response_bytes": 65536,
    },
)


def client_config(
    profiles: list[dict[str, Any]], domestic_prefix: str = ""
) -> tuple[dict[str, Any], list[int]]:
    if not profiles or len(profiles) > 128:
        raise ValueError("Unexpected profile count")
    config: dict[str, Any] = {
        "log": {"loglevel": "none"},
        "inbounds": [],
        "outbounds": [],
        "routing": {"rules": []},
    }
    ports: list[int] = []
    for index, profile in enumerate(profiles):
        for _ in range(32):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            if port not in ports:
                break
        else:
            raise ValueError("Could not allocate distinct probe ports")
        ports.append(port)
        tag = f"probe-{index}"
        config["inbounds"].append(
            {
                "tag": tag,
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "http",
                "settings": {},
            }
        )
        outbound = dict(profile["outbounds"][0], tag=tag)
        config["outbounds"].append(outbound)
        config["routing"]["rules"].append(
            {
                "type": "field",
                "inboundTag": [tag],
                "outboundTag": tag,
            }
        )
        if domestic_prefix and str(profile.get("remarks", "")).startswith(domestic_prefix):
            udp_tag = tag + "-udp"
            config["inbounds"].append(
                {
                    "tag": udp_tag,
                    "listen": "127.0.0.1",
                    "port": port,
                    "protocol": "dokodemo-door",
                    "settings": {
                        "address": OPTIONS["dns_address"],
                        "port": OPTIONS["dns_port"],
                        "network": "udp",
                    },
                }
            )
            config["routing"]["rules"].append(
                {"type": "field", "inboundTag": [udp_tag], "outboundTag": tag}
            )
    return config, ports


def check(
    port: int,
    urls: tuple[str, ...] = tuple(OPTIONS["urls"]),
) -> dict[str, Any]:
    start = time.monotonic()
    # Either destination succeeding is sufficient; one website's outage must not page us.
    for url in urls:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "--noproxy",
                    "",
                    "--proxy",
                    f"http://127.0.0.1:{port}",
                    "--connect-timeout",
                    str(OPTIONS["connect_timeout_seconds"]),
                    "--max-time",
                    str(OPTIONS["request_timeout_seconds"]),
                    "--max-filesize",
                    str(OPTIONS["max_response_bytes"]),
                    "--silent",
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code}",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=OPTIONS["process_timeout_seconds"],
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.isdigit() and 200 <= int(result.stdout) < 500:
            return {"healthy": True, "seconds": round(time.monotonic() - start, 2)}
    return {"healthy": False, "reason": "HTTPS through profile failed"}


def udp_check(port: int) -> bool:
    labels = str(OPTIONS["dns_query_name"]).rstrip(".").encode("idna").split(b".")
    if not labels or any(not 1 <= len(label) <= 63 for label in labels):
        raise ValueError("Invalid DNS probe name")
    question = b"".join(bytes([len(label)]) + label for label in labels) + b"\x00\x00\x01\x00\x01"
    query = struct.pack("!6H", 19272, 256, 1, 0, 0, 0) + question
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.settimeout(OPTIONS["udp_timeout_seconds"])
            connection.connect(("127.0.0.1", port))
            connection.send(query)
            response = connection.recv(4096)
        return (
            len(response) >= 12
            and response[:2] == query[:2]
            and bool(response[2] & 0x80)
            and response[3] & 15 == 0
            and struct.unpack("!H", response[6:8])[0] > 0
        )
    except OSError:
        return False


def check_entry(port: int, domestic: bool) -> dict[str, Any]:
    result = check(port)
    if not domestic or not result["healthy"]:
        return result
    foreign = check(port, tuple(OPTIONS["foreign_urls"]))
    local = check(port, tuple(OPTIONS["domestic_urls"]))
    udp = udp_check(port)
    result["policy_checks"] = {
        "foreign": foreign["healthy"],
        "domestic": local["healthy"],
        "udp": udp,
    }
    result["healthy"] = foreign["healthy"] and local["healthy"] and udp
    if not result["healthy"]:
        result["reason"] = "Domestic/foreign routing, trusted DNS or UDP carriage failed"
    return result


def _probe_group(
    profiles: list[dict[str, Any]], binary: Path, domestic_prefix: str = ""
) -> dict[str, dict[str, Any]]:
    config, ports = client_config(profiles, domestic_prefix)
    names = [str(profile.get("remarks", f"profile-{i}")) for i, profile in enumerate(profiles)]
    if len(set(names)) != len(names):
        raise ValueError("Profile names must be unique for monitoring")
    with tempfile.TemporaryDirectory(prefix="keyholder-probe-") as directory:
        path = Path(directory) / "client.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        process = subprocess.Popen(
            [str(binary), "run", "-config", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(OPTIONS["startup_attempts"]):
                if process.poll() is not None:
                    raise ValueError("Probe client could not start")
                try:
                    with socket.create_connection(("127.0.0.1", ports[-1]), timeout=0.1):
                        break
                except OSError:
                    time.sleep(OPTIONS["startup_interval_seconds"])
            else:
                raise ValueError("Probe client startup timed out")
            with concurrent.futures.ThreadPoolExecutor(max_workers=OPTIONS["workers"]) as pool:
                results = pool.map(
                    check_entry,
                    ports,
                    [bool(domestic_prefix and name.startswith(domestic_prefix)) for name in names],
                )
                return dict(zip(names, results, strict=True))
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def probe(
    profiles: list[dict[str, Any]], binary: Path, domestic_prefix: str = ""
) -> dict[str, dict[str, Any]]:
    if not profiles or len(profiles) > 128:
        raise ValueError("Unexpected profile count")
    names = [p.get("remarks") for p in profiles]
    if len(set(names)) != len(names):
        raise ValueError("Profile names must be unique for monitoring")
    if domestic_prefix and not any(str(name).startswith(domestic_prefix) for name in names):
        raise ValueError("Configured domestic monitoring profile is missing")
    # Mixed HTTP/1.1 and HTTP/2 clients produced false HTTPUpgrade failures in one core.
    # Keep TLS negotiation groups in separate processes, as an active client would.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for profile in profiles:
        stream = profile["outbounds"][0].get("streamSettings", {})
        security = stream.get("security", "none")
        key = (
            security,
            stream.get("network", "") if security == "reality" else "",
            *stream.get("tlsSettings", {}).get("alpn", []),
        )
        groups.setdefault(key, []).append(profile)
    results = {}
    for group in groups.values():
        results.update(_probe_group(group, binary, domestic_prefix))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="kh_monitor")
    parser.add_argument("--container", default="keyholder-api-1")
    parser.add_argument(
        "--domestic-prefix", default="", help="Enable split-routing canaries for matching names"
    )
    parser.add_argument("--binary", type=Path, default=Path("/var/lib/marzban/xray-core/xray"))
    parser.add_argument("--state", type=Path, default=Path("/var/lib/keyholder-monitor/proxy.json"))
    args = parser.parse_args()
    previous: dict[str, Any] = {}
    try:
        previous = json.loads(args.state.read_text())
    except (OSError, ValueError):
        pass
    # Ubuntu 22.04's host interpreter is Python 3.10.
    report: dict[str, Any] = {
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()  # noqa: UP017
    }
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                args.container,
                "/app/.venv/bin/python",
                "-c",
                EXPORT,
                args.username,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        if len(result.stdout) > 1024 * 1024:
            raise ValueError("Oversized subscription")
        report["profiles"] = probe(json.loads(result.stdout), args.binary, args.domestic_prefix)
        report["healthy"] = all(p["healthy"] for p in report["profiles"].values())
    except Exception as error:
        report.update(healthy=False, error=type(error).__name__, profiles={})
    for name, item in report["profiles"].items():
        old = previous.get("profiles", {}).get(name, {})
        item["failures"] = 0 if item["healthy"] else int(old.get("failures", 0)) + 1
    report["failures"] = 0 if report["healthy"] else int(previous.get("failures", 0)) + 1
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=args.state.parent, delete=False) as output:
        json.dump(report, output)
    os.replace(output.name, args.state)
    print(
        json.dumps(
            {
                "healthy": report["healthy"],
                "profiles": len(report["profiles"]),
                "failed": {
                    name: {key: item[key] for key in ("reason", "policy_checks") if key in item}
                    for name, item in report["profiles"].items()
                    if not item["healthy"]
                },
                **({"error": report["error"]} if "error" in report else {}),
            }
        )
    )
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
