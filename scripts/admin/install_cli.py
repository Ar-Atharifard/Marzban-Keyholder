#!/usr/bin/env python3
"""Refresh the server-side CLI from this checkout; no services are restarted."""

import argparse
import os
import tempfile
from pathlib import Path

MODULES = (
    "__init__.py",
    "profile_types.py",
    "inbounds.py",
    "personal.py",
    "cli.py",
    "billing_cli.py",
)
WRAPPER = """#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keyholder.cli import main

arguments = sys.argv[1:]
if "--local" not in arguments:
    arguments = ["--local", *arguments]
raise SystemExit(main(arguments))
"""


def write_atomic(destination: Path, contents: bytes, mode: int = 0o644) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor, filename = tempfile.mkstemp(prefix=".cli-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(contents)
        os.chmod(filename, mode)
        os.replace(filename, destination)
    finally:
        Path(filename).unlink(missing_ok=True)


def install(checkout: Path, prefix: Path) -> None:
    source = checkout / "src/keyholder"
    modules = {name: (source / name).read_bytes() for name in MODULES}
    manual = (checkout / "docs/keyholder.1").read_bytes()
    for name, contents in modules.items():
        compile(contents, name, "exec")
    directory = prefix / "lib/keyholder-admin"
    for name, contents in modules.items():
        write_atomic(directory / "keyholder" / name, contents)
    write_atomic(directory / "cli.py", WRAPPER.encode(), 0o755)
    write_atomic(prefix / "share/man/man1/keyholder.1", manual)
    link = prefix / "bin/keyholder"
    link.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if link.is_symlink() and link.resolve() == directory / "cli.py":
        return
    temporary = link.with_name(".keyholder-next")
    try:
        temporary.symlink_to(directory / "cli.py")
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path("/usr/local"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo on the server.")
    if not args.prefix.is_absolute():
        parser.error("The installation prefix must be absolute.")
    install(Path(__file__).resolve().parents[2], args.prefix)
    print("Server CLI and manual updated. No containers or services were restarted.")


if __name__ == "__main__":
    main()
