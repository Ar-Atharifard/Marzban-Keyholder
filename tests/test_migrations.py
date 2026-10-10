import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from scripts.backup_database import backup_database
from tests.conftest import ADMIN_KEY, KINDS

LEGACY = {
    "profiles": ["xhttp_reality", "tcp_reality", "xhttp_cdn", "ws_cdn"],
    "ech_enabled": True,
    "include_base_cdn": False,
}


@pytest.fixture
def migrated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    database = tmp_path / "legacy.db"
    monkeypatch.setenv("KEYHOLDER_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", ADMIN_KEY)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(config, "0001")
    with sqlite3.connect(database) as db:
        for cid, policy in [("first", LEGACY), ("second", {"profiles": ["ws_cdn"]})]:
            db.execute(
                "INSERT INTO customers "
                "(id,name,status,token_hash,policy,created_at,updated_at) "
                "VALUES (?,?,'active',?,?,'2026-10-01','2026-10-01')",
                (cid, "Fixture", f"fixture-hash-{cid}", json.dumps(policy)),
            )
            db.execute(
                "INSERT INTO customer_mappings VALUES (?, 'marzban-default', 'alice')", (cid,)
            )
        db.execute(
            "INSERT INTO application_data VALUES ('ech', ?, '2026-10-01')",
            (json.dumps({"ech_config_list": "fixture-legacy-ech"}),),
        )
    return config, database


def test_upgrade_and_downgrade_preserve_identity_and_restore_policy(
    migrated_database: tuple[Config, Path],
) -> None:
    config, database = migrated_database
    with sqlite3.connect(database) as db:
        original = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
        mappings = db.execute("SELECT * FROM customer_mappings ORDER BY customer_id").fetchall()
    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database) as db:
        policies = {
            cid: json.loads(value) for cid, value in db.execute("SELECT id,policy FROM customers")
        }
        assert policies == {
            "first": {"profiles": KINDS},
            "second": {"profiles": KINDS},
        }
        assert (
            db.execute("SELECT * FROM customer_mappings ORDER BY customer_id").fetchall()
            == mappings
        )
        assert db.execute("SELECT count(*) FROM application_data").fetchone() == (3,)
        assert db.execute("SELECT token_hash FROM customers ORDER BY id").fetchall() == [
            (row[3],) for row in original
        ]
    command.downgrade(config, "0001")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM customers ORDER BY id").fetchall() == original
        assert (
            db.execute("SELECT * FROM customer_mappings ORDER BY customer_id").fetchall()
            == mappings
        )
        assert db.execute("SELECT key FROM application_data").fetchall() == [("ech",)]
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0001",)


def test_downgrade_rejects_admin_edits_before_restoring_any_customer(
    migrated_database: tuple[Config, Path],
) -> None:
    config, database = migrated_database
    command.upgrade(config, "head")
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE customers SET policy=? WHERE id='second'",
            (json.dumps({"profiles": ["grpc_cdn"]}),),
        )
        before = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    with pytest.raises(RuntimeError, match="Policy changed after migration"):
        command.downgrade(config, "0001")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM customers ORDER BY id").fetchall() == before
        assert db.execute("SELECT count(*) FROM application_data").fetchone() == (3,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)


def test_repeated_upgrade_does_not_duplicate_archives(
    migrated_database: tuple[Config, Path],
) -> None:
    config, database = migrated_database
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM application_data").fetchone() == (3,)


def test_backup_restore_rehearsal_preserves_complete_legacy_state(
    migrated_database: tuple[Config, Path], tmp_path: Path
) -> None:
    config, database = migrated_database
    backup = tmp_path / "pre-release-backup.db"
    restored = tmp_path / "restore-rehearsal.db"
    tables = ["customers", "customer_mappings", "backends", "application_data", "alembic_version"]
    with sqlite3.connect(database) as db:
        before = {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables
        }
    backup_database(database, backup)
    command.upgrade(config, "head")
    # Rehearse restoration into an isolated file; never overwrite the migrated source.
    backup_database(backup, restored)
    with sqlite3.connect(restored) as db:
        after = {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables
        }
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert after == before
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)
