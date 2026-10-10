import sqlite3
from pathlib import Path

import pytest

from scripts.backup_database import backup_database


def test_backup_includes_committed_wal_and_preserves_identity(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "backup.db"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, token_hash TEXT)")
        db.execute("INSERT INTO customers VALUES ('fixture-id', 'fixture-hash')")
        db.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        backup_database(source, target)
        # Source connection remains open: backup must include the committed WAL transaction.
        with sqlite3.connect(target) as restored:
            assert restored.execute("SELECT * FROM customers").fetchall() == [
                ("fixture-id", "fixture-hash")
            ]
    assert target.stat().st_mode & 0o777 == 0o600


def test_backup_refuses_overwrite_and_missing_source(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE fixture (id INTEGER)")
    target = tmp_path / "existing.db"
    target.write_bytes(b"preserve-existing-file")
    with pytest.raises(FileExistsError):
        backup_database(source, target)
    assert target.read_bytes() == b"preserve-existing-file"
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.db", tmp_path / "new.db")
    assert not (tmp_path / "new.db").exists()


def test_failed_backup_removes_only_its_new_file(tmp_path: Path) -> None:
    source = tmp_path / "broken.db"
    source.write_bytes(b"not a SQLite database")
    target = tmp_path / "backup.db"
    with pytest.raises(sqlite3.DatabaseError):
        backup_database(source, target)
    assert not target.exists()
    assert source.read_bytes() == b"not a SQLite database"


def test_backup_refuses_same_source_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE fixture (id INTEGER)")
    with pytest.raises(ValueError):
        backup_database(source, source)
    link = tmp_path / "symlink.db"
    link.symlink_to(source)
    with pytest.raises(ValueError):
        backup_database(source, link)
