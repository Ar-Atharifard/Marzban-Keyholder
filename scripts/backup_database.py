"""Create a private, consistent SQLite backup without copying live WAL files."""

import argparse
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path, timeout: float = 30) -> None:
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if source == destination.resolve():
        raise ValueError("Backup destination must differ from source")
    # O_EXCL refuses existing files and symlinks; backups contain sensitive credentials.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    deadline = time.monotonic() + timeout

    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("Backup deadline exceeded")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as reader:
            with closing(sqlite3.connect(destination, timeout=1)) as writer:
                reader.backup(writer, pages=64, progress=progress, sleep=0.05)
                writer.execute("PRAGMA journal_mode=DELETE")
                if writer.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Backup integrity check failed")
                if writer.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("Backup foreign key check failed")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        backup_database(args.source, args.destination, args.timeout)
    except (OSError, sqlite3.Error, ValueError, TimeoutError):
        # Database errors and paths can contain private values: do not print exceptions.
        parser.exit(1, "Backup failed; check paths, permissions, database integrity and timeout.\n")
    print("Backup created and integrity checked. Treat it as a production secret.")


if __name__ == "__main__":
    main()
