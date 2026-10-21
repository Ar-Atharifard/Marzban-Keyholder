"""Local recovery tools; never part of customer accounting or proxy configuration."""

import os
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def run_masque(
    binary: Path | None,
    state: Path | None,
    port: int,
    ipv6: bool,
    no_fragment: bool,
    *,
    scan: str = "balanced",
    fresh: bool = False,
    register: bool = False,
    register_proxy: str | None = None,
) -> int:
    executable = str(binary) if binary else shutil.which("aether")
    if not executable or not Path(executable).is_file():
        raise ValueError("Install a verified official Aether release; use --binary PATH.")
    if not 1024 <= port <= 65535:
        raise ValueError("Use a loopback port between 1024 and 65535.")
    if scan not in {"turbo", "balanced", "thorough", "stealth", "ironclad"}:
        raise ValueError("Unknown endpoint scan mode.")
    if register_proxy:
        proxy = urlsplit(register_proxy)
        if (
            not register
            or proxy.scheme not in {"http", "https", "socks5", "socks5h"}
            or proxy.hostname not in {"127.0.0.1", "::1", "localhost"}
            or not proxy.port
            or proxy.username
            or proxy.password
            or proxy.query
            or proxy.fragment
            or proxy.path not in {"", "/"}
        ):
            raise ValueError(
                "--register-proxy requires --register and a credential-free loopback URL."
            )
    if not register:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    directory = state or Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / (
        "keyholder/masque"
    )
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    # Aether's identity files contain private keys, including files created on reconnect.
    previous_umask = os.umask(0o077)
    command = [
        str(Path(executable).expanduser().resolve()),
        "--masque",
        "--h2",
        "--bind",
        f"127.0.0.1:{port}",
        "--masque-config",
        str(directory / "identity.toml"),
        "--config",
        str(directory / "aether.toml"),
        "--scan",
        scan,
        "--no-quick-reconnect" if fresh else "--quick-reconnect",
        "--perf",
        "low",
        "--startup-secs",
        "60",
        "--log-level",
        "warn",
        "-6" if ipv6 else "-4",
        "--no-fragment" if no_fragment else "--fragment",
    ]
    if register:
        command += ["--register", "masque"]
        if register_proxy:
            command += ["--upstream", register_proxy]
    environment = {k: v for k, v in os.environ.items() if not k.startswith("AETHER_")}
    if register:
        print("Register administrator WARP keys only; no tunnel or listener is started.")
    else:
        print(f"Administrator recovery SOCKS: 127.0.0.1:{port}. Ctrl+C stops it.")
    print("Independent Cloudflare WARP connection; Marzban quota and routing do not apply.")
    try:
        return subprocess.run(command, cwd=directory, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 130
    finally:
        os.umask(previous_umask)
