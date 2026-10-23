import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import monitor, recovery
from scripts.storage_budget import Budget


def state(size: int = 5_800_000_000) -> dict[str, Any]:
    return {
        "enabled": True,
        "cleanup_enabled": False,
        "recovery_cleanup_enabled": True,
        "total_bytes": 10_000_000_000,
        "accounted_bytes": size,
        "blocked": False,
        "scopes": {
            "receipts": {
                "percent": 0,
                "used_bytes": 0,
                "budget_bytes": 2_000_000_000,
                "stale": False,
            },
            "recovery": {
                "percent": size / 6_000_000_000 * 100,
                "used_bytes": size,
                "budget_bytes": 6_000_000_000,
                "stale": False,
            },
        },
    }


def budget_with_measurements(
    monkeypatch: pytest.MonkeyPatch, measurements: list[int]
) -> tuple[Budget, list[dict[str, Any]]]:
    budget = Budget.__new__(Budget)
    reports: list[dict[str, Any]] = []
    values = iter(measurements)
    monkeypatch.setattr(budget, "measure", lambda: state(next(values)))
    monkeypatch.setattr(budget, "save_status", lambda **kwargs: reports.append(kwargs))
    return budget, reports


def snapshots(count: int = 4) -> list[dict[str, Any]]:
    return [
        {"id": letter * 64, "time": f"2026-10-{day:02d}T00:00:00Z"}
        for day, letter in enumerate("abcd"[:count], 1)
    ]


def test_capacity_cleanup_protects_latest_two_and_waits_for_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, reports = budget_with_measurements(monkeypatch, [5_800_000_000, 5_800_000_000])
    calls = []

    def run(command: list[str], timeout: int) -> bytes:
        calls.append(command)
        return json.dumps(snapshots()).encode() if command[1] == "snapshots" else b""

    budget.maintain(run, "synthetic")
    assert [c[2] for c in calls if c[1] == "forget"] == ["a" * 64]
    assert calls[0][calls[0].index("--tag") + 1] == "keyholder-recovery-v1,keyholder-complete"
    assert reports[-1]["cleanup"] == "awaiting-version-reclamation"


def test_capacity_cleanup_stops_at_target_and_checks_after_pruning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, reports = budget_with_measurements(monkeypatch, [5_800_000_000, 4_700_000_000])
    calls = []

    def run(command: list[str], timeout: int) -> bytes:
        calls.append(command)
        return json.dumps(snapshots()).encode() if command[1] == "snapshots" else b""

    budget.maintain(run, "synthetic")
    assert [c[1] for c in calls] == ["snapshots", "forget", "prune", "check"]
    assert reports[-1]["cleanup"] == "capacity-reclaimed"


def test_protected_floor_refuses_deleting_last_restore_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, reports = budget_with_measurements(monkeypatch, [5_800_000_000])
    calls = []

    def run(command: list[str], timeout: int) -> bytes:
        calls.append(command)
        return json.dumps(snapshots(2)).encode()

    with pytest.raises(ValueError, match="protected"):
        budget.maintain(run, "synthetic")
    assert all(c[1] != "forget" for c in calls)
    assert reports[-1]["blocked"]


def test_budget_block_happens_before_any_upload_or_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = tmp_path / "password"
    password.write_text("synthetic")
    password.chmod(0o600)
    source = tmp_path / "config.txt"
    source.write_text("synthetic")
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:prefix")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))

    class Refusal:
        def __init__(self, *args: Any):
            pass

        def start(self) -> None:
            pass

        def capture_receipts(self, bundle: Path) -> None:
            pass

        def release_capture(self) -> None:
            pass

        def admit(self, bundle: Path) -> None:
            raise ValueError("Storage exhausted")

        def finish(self, success: bool) -> None:
            assert not success

    monkeypatch.setattr(recovery, "Budget", Refusal)
    calls = []
    monkeypatch.setattr(recovery, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="exhausted"):
        recovery.upload(
            {
                "service_id": "synthetic",
                "files": {"rootfs/config.txt": str(source)},
                "storage": {} | {"api_env_file": "unused"},
            },
            work,
            tmp_path / "status.json",
        )
    assert calls == []
    assert not (tmp_path / "status.json").exists()
    assert not (work / "bundle").exists()


def test_storage_monitor_thresholds_and_resolution(tmp_path: Path) -> None:
    path = tmp_path / "storage.json"
    value = state()
    timestamp = dt.datetime(2026, 10, 23, tzinfo=dt.UTC)
    value["checked_at"] = timestamp.isoformat()
    path.write_text(json.dumps(value))
    config = {"storage_status_file": str(path), "storage_status_max_age_hours": 26}
    alerts = monitor.storage_alerts(config, timestamp.timestamp())
    assert any("critical" in message for message in alerts.values())
    assert all(monitor.severity_for_key(key) == "critical" for key in alerts)
    value["scopes"]["recovery"]["percent"] = 0
    path.write_text(json.dumps(value))
    assert monitor.storage_alerts(config, timestamp.timestamp()) == {}
    assert "storage:status" in monitor.storage_alerts(config, timestamp.timestamp() + 27 * 3600)


@pytest.mark.parametrize("summary_id", ["a" * 8, "a" * 64])
def test_successful_budgeted_backup_marks_only_complete_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, summary_id: str
) -> None:
    source = tmp_path / "config.txt"
    source.write_text("synthetic")
    password = tmp_path / "password"
    password.write_text("synthetic")
    password.chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:prefix")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))
    lifecycle = []

    class Admission:
        def __init__(self, *args: Any):
            pass

        def start(self) -> None:
            lifecycle.append("lock")

        def capture_receipts(self, bundle: Path) -> None:
            lifecycle.append("images")

        def release_capture(self) -> None:
            lifecycle.append("unlock")

        def admit(self, bundle: Path) -> None:
            lifecycle.append("reserve")

        def finish(self, success: bool) -> None:
            lifecycle.append("success" if success else "failed")

        def api(self, *args: Any) -> Any:
            return state(1)

    monkeypatch.setattr(recovery, "Budget", Admission)
    calls = []

    def run(command: list[str], timeout: int = 60) -> bytes:
        calls.append(command)
        return (
            json.dumps({"message_type": "summary", "snapshot_id": summary_id}).encode()
            if command[1] == "backup"
            else json.dumps([{"id": "a" * 64}]).encode()
            if command[1] == "snapshots"
            else b"{}"
        )

    monkeypatch.setattr(recovery, "run", run)
    recovery.upload(
        {
            "service_id": "synthetic",
            "files": {"rootfs/config.txt": str(source)},
            "storage": {"api_env_file": "unused"},
        },
        work,
        tmp_path / "status.json",
    )
    assert lifecycle == ["lock", "images", "unlock", "reserve", "success"]
    assert [c[1] for c in calls] == (
        ["backup", "snapshots", "tag", "forget"]
        if len(summary_id) == 8
        else ["backup", "tag", "forget"]
    )
    assert next(c for c in calls if c[1] == "tag") == [
        "restic",
        "tag",
        "--add",
        "keyholder-complete",
        "a" * 64,
    ]
    assert "keyholder-recovery-v1,keyholder-complete" in calls[-1]
    assert (tmp_path / "status.json").is_file()


def test_incomplete_backup_never_marks_or_forgets_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    source = tmp_path / "config.txt"
    source.write_text("synthetic")
    password = tmp_path / "password"
    password.write_text("synthetic")
    password.chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:prefix")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))

    class Admission:
        def __init__(self, *args: Any):
            pass

        def start(self) -> None:
            pass

        def capture_receipts(self, bundle: Path) -> None:
            pass

        def release_capture(self) -> None:
            pass

        def admit(self, bundle: Path) -> None:
            pass

        def finish(self, success: bool) -> None:
            assert not success

    monkeypatch.setattr(recovery, "Budget", Admission)
    calls = []

    def run(command: list[str], timeout: int = 60) -> bytes:
        calls.append(command)
        raise subprocess.CalledProcessError(3, command)

    monkeypatch.setattr(recovery, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        recovery.upload(
            {
                "service_id": "synthetic",
                "files": {"rootfs/config.txt": str(source)},
                "storage": {"api_env_file": "unused"},
            },
            work,
            tmp_path / "status.json",
        )
    assert [c[1] for c in calls] == ["backup"]
    assert not (tmp_path / "status.json").exists()


def test_version_inventory_counts_hidden_and_unfinished_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from scripts import storage_budget

    calls = []
    responses = iter(
        [
            {
                "allowed": {"bucketId": "synthetic-bucket", "bucketName": "synthetic"},
                "apiUrl": "https://api001.backblazeb2.com",
                "authorizationToken": "synthetic-token",
            },
            {
                "files": [{"contentLength": 100}, {"contentLength": 50}, {"contentLength": 0}],
                "nextFileName": None,
            },
            {"files": [{"fileId": "unfinished"}]},
            {"parts": [{"contentLength": 25}]},
        ]
    )

    class Opener:
        def open(self, request: Any, timeout: int) -> Any:
            calls.append(request.full_url)
            return io.BytesIO(json.dumps(next(responses)).encode())

    import urllib.request

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    assert (
        storage_budget.repository_bytes(
            {
                "AWS_ACCESS_KEY_ID": "synthetic-id",
                "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                "RESTIC_REPOSITORY": "s3:https://s3.example.backblazeb2.com/synthetic/keyholder",
            }
        )
        == 175
    )
    assert calls[-1].endswith("b2_list_parts")


def test_capacity_preview_never_deletes_snapshots_or_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, _ = budget_with_measurements(monkeypatch, [5_800_000_000])
    calls = []

    def run(command: list[str], timeout: int) -> bytes:
        calls.append(command)
        return (
            json.dumps(snapshots()).encode() if command[1] == "snapshots" else b"Prune preview only"
        )

    result = budget.preview(run, "synthetic")
    assert [s["id"] for s in result["protected_snapshots"]] == ["d" * 64, "c" * 64]
    assert [s["id"] for s in result["oldest_first_candidates"]] == ["a" * 64, "b" * 64]
    assert all("--dry-run" in c for c in calls if c[1] == "prune")
    assert all(c[1] != "forget" for c in calls)


def test_rate_limited_capture_retries_with_same_request_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import urllib.error
    import urllib.request
    from email.message import Message

    budget = Budget.__new__(Budget)
    budget.url, budget.key = "http://127.0.0.1:18000", "synthetic-key"
    keys, waits = [], []

    class Opener:
        def open(self, request: Any, timeout: int) -> Any:
            keys.append(request.get_header("Idempotency-key"))
            if len(keys) == 1:
                headers = Message()
                headers["Retry-After"] = "1"
                raise urllib.error.HTTPError(request.full_url, 429, "Limited", headers, None)
            return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr("scripts.storage_budget.time.sleep", lambda delay: waits.append(delay))
    assert budget.api("POST", "/storage/reconcile") == {"ok": True}
    assert keys[0] == keys[1] and keys[0]
    assert waits == [1]
