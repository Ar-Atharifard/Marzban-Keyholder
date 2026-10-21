#!/usr/bin/python3
"""Fetch the domestic recovery archive before the normal encrypted backup."""

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path


def validate_archive(path: Path) -> None:
    if not 1024 < path.stat().st_size <= 160 * 1024**2:
        raise ValueError("Unexpected domestic recovery archive size")
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if not members or len(members) > 1000:
            raise ValueError("Unexpected domestic recovery archive entries")
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe domestic recovery archive member")
            if member.size > 80 * 1024**2:
                raise ValueError("Oversize domestic recovery archive member")


def main() -> None:
    target = Path("/var/lib/keyholder-recovery/domestic/gate.tar")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".gate-")
    try:
        with os.fdopen(descriptor, "wb") as output:
            subprocess.run(
                [
                    "ssh",
                    "-F",
                    "/etc/keyholder/domestic-monitor.ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=3",
                    "domestic",
                    "backup",
                ],
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=True,
            )
        path = Path(temporary)
        validate_archive(path)
        path.replace(target)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
