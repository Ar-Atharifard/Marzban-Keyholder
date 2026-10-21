#!/usr/bin/python3
"""Private DNS-01 certificate setup and renewal using a pinned lego binary."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path("/etc/keyholder/acme")
CERTS = Path("/opt/braavos-gateway/certs")


def private_write(path: Path, value: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(value)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(settings: dict[str, Any]) -> dict[str, Any]:
    domain, email, token = (
        str(settings.get(key, "")).strip() for key in ["domain", "email", "token"]
    )
    if (
        not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", domain)
        or "." not in domain
    ):
        raise ValueError("Invalid certificate domain")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Invalid certificate contact email")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", token):
        raise ValueError("Invalid Cloudflare API token format")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing = ROOT / "settings.json"
    if existing.exists() and json.loads(existing.read_text())["domain"] != domain:
        raise ValueError("Changing the existing subscription hostname needs a migration review")
    private_write(ROOT / "token", token)
    private_write(ROOT / "settings.json", json.dumps({"domain": domain, "email": email}))
    (ROOT / "setup-error.json").unlink(missing_ok=True)
    subprocess.run(
        ["systemctl", "enable", "--now", "keyholder-tls.timer"],
        check=True,
        capture_output=True,
        timeout=15,
    )
    subprocess.run(
        ["systemctl", "start", "--no-block", "keyholder-tls.service"],
        check=True,
        capture_output=True,
        timeout=15,
    )
    return {"configured": True, "issuance_started": True}


def issue() -> None:
    settings = json.loads((ROOT / "settings.json").read_text())
    domain = settings["domain"]
    command = [
        "/usr/local/bin/lego",
        "run",
        "--path",
        str(ROOT / "state"),
        "--email",
        settings["email"],
        "--domains",
        domain,
        "--dns",
        "cloudflare",
        "--key-type",
        "ec256",
        "--accept-tos",
    ]
    source = ROOT / "state/certificates" / (domain + ".crt")
    command += ["--renew-days", "30"]
    environment = dict(os.environ, CF_DNS_API_TOKEN_FILE=str(ROOT / "token"))
    result = subprocess.run(command, capture_output=True, timeout=600, env=environment)
    if result.returncode:
        private_write(ROOT / "last-error.txt", result.stderr.decode(errors="replace"))
        raise RuntimeError("Certificate issuance/renewal failed; private diagnostics retained")
    key = source.with_suffix(".key")
    subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            str(source),
            "-noout",
            "-checkhost",
            domain,
            "-checkend",
            "604800",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    before = [
        (path, path.read_bytes() if path.exists() else None)
        for path in [CERTS / "subscription.crt", CERTS / "subscription.key"]
    ]
    try:
        private_write(before[0][0], source.read_text())
        private_write(before[1][0], key.read_text())
        subprocess.run(
            ["docker", "exec", "braavos-gateway", "nginx", "-t"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            ["docker", "exec", "braavos-gateway", "nginx", "-s", "reload"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        for path, value in before:
            if value is None:
                path.unlink(missing_ok=True)
            else:
                private_write(path, value.decode())
        raise
    (ROOT / "last-error.txt").unlink(missing_ok=True)
    (ROOT / "setup-error.json").unlink(missing_ok=True)


def status() -> dict[str, Any]:
    result: dict[str, Any] = {
        "configured": (ROOT / "settings.json").exists(),
        "certificate_ready": False,
    }
    certificate = CERTS / "subscription.crt"
    if certificate.exists():
        response = subprocess.run(
            ["openssl", "x509", "-in", str(certificate), "-noout", "-enddate"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        result.update(
            certificate_ready=True, expires=response.stdout.strip().removeprefix("notAfter=")
        )
    response = subprocess.run(
        ["systemctl", "show", "keyholder-tls.service", "-p", "ActiveState", "-p", "Result"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    result.update(dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line))
    if (ROOT / "setup-error.json").exists():
        result["setup_error"] = json.loads((ROOT / "setup-error.json").read_text())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["configure", "issue", "status"])
    action = parser.parse_args().action
    if action == "configure":
        print(json.dumps(configure(json.load(sys.stdin))))
    elif action == "issue":
        issue()
    else:
        print(json.dumps(status()))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        report = {"type": type(error).__name__}
        if isinstance(error, ValueError):
            report["reason"] = str(error)
        private_write(ROOT / "setup-error.json", json.dumps(report))
        print("TLS operation failed; inspect the private setup or service status.", file=sys.stderr)
        raise SystemExit(1) from None
