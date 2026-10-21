#!/usr/bin/python3
"""Stage a private domestic archive; never apply its firewall or SSH configuration."""

import argparse
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from scripts.gate_backup import FILES
    from scripts.gate_snapshot import validate_archive
else:
    from gate_backup import FILES
    from gate_snapshot import validate_archive


def stage(archive_path: Path, destination: Path) -> None:
    validate_archive(archive_path)
    if destination.exists():
        raise ValueError("Staging destination already exists; inspect it before retrying")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".domestic-") as temporary:
        root = Path(temporary) / "staged"
        root.mkdir(mode=0o700)
        with tarfile.open(archive_path) as archive:
            for member in archive:
                if not any(
                    member.name == name or member.name.startswith(name + "/") for name in FILES
                ):
                    raise ValueError("Unexpected file in domestic recovery archive")
                path = root / member.name
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("Missing archive contents")
                    with source, path.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    path.chmod(0o700 if member.mode & 0o111 else 0o600)
        for required in [
            "opt/marzban-node/main.py",
            "opt/marzban-node/requirements.txt",
            "opt/marzban-node/assets/xray",
            "usr/local/bin/rathole",
            "etc/marzban-node/node.env",
            "etc/keyholder-rathole/server.toml",
            "etc/haproxy/haproxy.cfg",
        ]:
            if not (root / required).is_file():
                raise ValueError("Domestic archive is incomplete")
        if not list((root / "var/cache/keyholder-node-wheels").glob("*.whl")):
            raise ValueError("Domestic archive lacks pinned dependency wheels")
        root.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        stage(args.archive, args.destination)
    except (OSError, ValueError, tarfile.TarError):
        raise SystemExit(
            "Domestic staging failed; inspect the private archive and destination"
        ) from None
