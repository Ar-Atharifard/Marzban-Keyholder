import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from scripts.verify_recovery import compare_core, compare_database, compare_panel, run


def test_restored_identity_is_exact_and_extra_rows_fail(tmp_path: Path) -> None:
    before, after = tmp_path / "before.db", tmp_path / "after.db"
    for path in (before, after):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE customers (id TEXT, token_hash TEXT)")
            db.execute("INSERT INTO customers VALUES ('stable', 'hash')")
    assert compare_database(before, after) == 1
    with sqlite3.connect(after) as db:
        db.execute("INSERT INTO customers VALUES ('duplicate', 'hash2')")
    with pytest.raises(ValueError, match="differs"):
        compare_database(before, after)


def test_panel_usage_may_advance_but_plan_changes_fail(tmp_path: Path) -> None:
    before, after = tmp_path / "before.db", tmp_path / "after.db"
    for path in (before, after):
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE users (id INT,username TEXT,data_limit INT,expire INT,used INT)"
            )
            db.execute("INSERT INTO users VALUES (1,'synthetic',1000,2000000000,0)")
    with sqlite3.connect(after) as db:
        db.execute("UPDATE users SET used=100")
    assert compare_panel(before, after) == 1
    with sqlite3.connect(after) as db:
        db.execute("UPDATE users SET data_limit=2000")
    with pytest.raises(ValueError, match="plans differ"):
        compare_panel(before, after)


def test_core_allows_new_listener_but_refuses_key_changes(tmp_path: Path) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    original = {"inbounds": [{"listen": "192.0.2.1", "port": 443, "key": "synthetic"}]}
    before.write_text(json.dumps(original))
    original["inbounds"][0]["listen"] = "127.0.0.1"
    after.write_text(json.dumps(original))
    assert compare_core(before, after) == 1
    original["inbounds"][0]["key"] = "changed"
    after.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="settings differ"):
        compare_core(before, after)


def test_failed_tool_output_is_not_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "private-token", "private-password")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(ValueError) as error:
        run(["synthetic"])
    assert "private-token" not in str(error.value)
    assert "private-password" not in str(error.value)


def test_admin_traffic_can_grow_without_weakening_credential_checks(tmp_path: Path) -> None:
    before, after = tmp_path / "before.db", tmp_path / "after.db"
    for path in (before, after):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE users (id INT,username TEXT,data_limit INT,expire INT)")
            db.execute("INSERT INTO users VALUES (1,'synthetic',1000,2000000000)")
            db.execute("CREATE TABLE admins (id INT, hashed_password TEXT, users_usage INT)")
            db.execute("INSERT INTO admins VALUES (1,'synthetic-hash',10)")
    with sqlite3.connect(after) as db:
        db.execute("UPDATE admins SET users_usage=100")
    assert compare_panel(before, after) == 1
    with sqlite3.connect(after) as db:
        db.execute("UPDATE admins SET hashed_password='changed'")
    with pytest.raises(ValueError, match="administrator credentials"):
        compare_panel(before, after)
    with sqlite3.connect(after) as db:
        db.execute("UPDATE admins SET hashed_password='synthetic-hash',users_usage=1")
    with pytest.raises(ValueError, match="counter decreased"):
        compare_panel(before, after)
