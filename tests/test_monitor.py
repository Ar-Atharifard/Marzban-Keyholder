import datetime as dt
import json
import sqlite3
from pathlib import Path

from scripts import monitor


def database(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE users (
          id INTEGER PRIMARY KEY, username TEXT, status TEXT, used_traffic INTEGER,
          data_limit INTEGER, expire INTEGER
        );
        CREATE TABLE node_user_usages (
          id INTEGER PRIMARY KEY, created_at DATETIME, user_id INTEGER,
          node_id INTEGER, used_traffic INTEGER
        );
        """
    )
    db.commit()
    db.close()


def config(path: Path) -> dict[str, object]:
    return {
        "marzban_db": str(path),
        "required_user_count": 1,
        "quota_warning_percent": [80, 95],
        "expiry_warning_days": [7, 3, 1],
        "traffic_min_gib": 1,
        "traffic_rate_gib_per_hour": 20,
        "traffic_baseline_multiplier": 3,
    }


def test_user_quota_expiry_and_status_come_from_marzban(tmp_path: Path) -> None:
    path = tmp_path / "marzban.sqlite3"
    database(path)
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    db = sqlite3.connect(path)
    db.execute(
        "INSERT INTO users VALUES (1, 'alice', 'disabled', ?, ?, ?)",
        (96 * monitor.GIB, 100 * monitor.GIB, int(now.timestamp() + 2 * 86400)),
    )
    db.commit()
    db.close()
    alerts, counters = monitor.user_alerts(config(path), {}, now)
    assert counters == {"1": 96 * monitor.GIB}
    assert set(alerts) == {"user:1:status", "user:1:quota", "user:1:expiry"}
    assert "alice" in " ".join(alerts.values())


def test_traffic_anomaly_requires_absolute_and_relative_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "marzban.sqlite3"
    database(path)
    now = dt.datetime(2026, 1, 8, 12, tzinfo=dt.UTC)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users VALUES (1, 'alice', 'active', ?, NULL, NULL)", (6 * monitor.GIB,))
    db.execute(
        "INSERT INTO node_user_usages VALUES (1, '2026-01-08 10:00:00', 1, NULL, ?)",
        (2 * monitor.GIB,),
    )
    db.commit()
    db.close()
    previous = {"sampled_at": now.timestamp() - 900, "user_counters": {"1": 0}}
    alerts, _ = monitor.user_alerts(config(path), previous, now)
    assert "user:1:traffic" in alerts


def test_state_is_private_and_public_result_omits_counters(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    monitor.save_state(path, {"healthy": True, "user_counters": {"1": 5}})
    assert path.stat().st_mode & 0o777 == 0o600
    assert "user_counters" not in monitor.public_result(json.loads(path.read_text()))


def test_missing_telegram_credentials_do_not_mark_alert_delivered(tmp_path: Path) -> None:
    config_path = tmp_path / "monitor.json"
    state_path = tmp_path / "state.json"
    db_path = tmp_path / "marzban.sqlite3"
    backup = tmp_path / "backup"
    backup.mkdir()
    database(db_path)
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO users VALUES (1, 'alice', 'limited', 0, NULL, NULL)")
    db.commit()
    db.close()
    supplied = {
        "state_file": str(state_path),
        "secrets_file": str(tmp_path / "missing.env"),
        "marzban_db": str(db_path),
        "backup_dir": str(backup),
        "backup_max_age_hours": 999999,
    }
    config_path.write_text(json.dumps(supplied))
    result = monitor.run(monitor.load_config(config_path), notify=True)
    assert result["alerts"]
    assert result["notified_alerts"] == {}
