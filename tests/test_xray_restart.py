import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import xray_restart


@pytest.fixture
def config() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(Path("deploy/xray-restart.example.json").read_text())
    return value


def test_invalid_config_cannot_enable_schedule(tmp_path: Path, config: dict[str, Any]) -> None:
    path = tmp_path / "restart.json"
    path.write_text(json.dumps({**config, "enabled": "false"}))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="boolean"):
        xray_restart.load_config(path)
    path.write_text(json.dumps({**config, "on_calendar": "daily\nUnit=docker.service"}))
    with pytest.raises(ValueError, match="calendar"):
        xray_restart.load_config(path)
    path.write_text(json.dumps({**config, "listeners": [{"host": "0.0.0.0", "port": 80}]}))
    with pytest.raises(ValueError, match="loopback"):
        xray_restart.load_config(path)


@pytest.mark.parametrize("enabled", [False, True])
def test_schedule_enable_disable_and_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], enabled: bool
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(xray_restart, "checked", lambda argv, *a, **kw: calls.append(argv))
    config.update(enabled=enabled, on_calendar="*-*-* 04:00:00 Asia/Tehran")
    xray_restart.apply(config, tmp_path / "restart.json", tmp_path)
    timer = (tmp_path / xray_restart.TIMER).read_text()
    assert "OnCalendar=*-*-* 04:00:00 Asia/Tehran" in timer
    assert "Persistent=false" in timer
    assert (["systemctl", "restart", xray_restart.TIMER] in calls) == enabled
    assert (["systemctl", "disable", "--now", xray_restart.TIMER] in calls) != enabled
    assert not any(
        call[:2] == ["systemctl", "restart"] and call[-1].endswith(".service") for call in calls
    )


def test_invalid_calendar_preserves_existing_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]
) -> None:
    timer = tmp_path / xray_restart.TIMER
    timer.write_text("original")

    def fail(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("invalid calendar")

    monkeypatch.setattr(xray_restart, "checked", fail)
    with pytest.raises(RuntimeError):
        xray_restart.apply(config, tmp_path / "restart.json", tmp_path)
    assert timer.read_text() == "original"


@pytest.mark.parametrize("check_only,enabled", [(True, True), (False, False)])
def test_dry_check_and_disabled_config_do_not_restart(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], check_only: bool, enabled: bool
) -> None:
    config["enabled"] = enabled
    calls: list[list[str]] = []
    monkeypatch.setattr(xray_restart, "active_pid", lambda cfg: 123)
    monkeypatch.setattr(xray_restart, "checked", lambda argv, *a, **kw: calls.append(argv))
    xray_restart.restart(config, check_only=check_only)
    assert len(calls) == 1 and "-test" in calls[0]


def test_bad_xray_config_never_stops_running_service(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]
) -> None:
    config["enabled"] = True
    monkeypatch.setattr(xray_restart, "active_pid", lambda cfg: 123)
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "sensitive validation output")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError) as error:
        xray_restart.restart(config)
    assert "sensitive" not in str(error.value)
    assert len(calls) == 1 and "-test" in calls[0]


@pytest.mark.parametrize("ready", [True, False])
def test_restart_checks_readiness_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], ready: bool
) -> None:
    from contextlib import nullcontext

    config["enabled"] = True
    calls: list[list[str]] = []
    monkeypatch.setattr(xray_restart, "active_pid", lambda cfg: 123)
    monkeypatch.setattr(xray_restart, "checked", lambda argv, *a, **kw: calls.append(argv))
    times = iter([0.0, 0.1, 100.0])
    monkeypatch.setattr("scripts.xray_restart.time.monotonic", lambda: next(times))
    monkeypatch.setattr("scripts.xray_restart.time.sleep", lambda _: None)

    def connect(*args: Any, **kwargs: Any) -> Any:
        if not ready:
            raise ConnectionRefusedError()
        return nullcontext()

    monkeypatch.setattr("scripts.xray_restart.socket.create_connection", connect)
    if ready:
        xray_restart.restart(config)
    else:
        with pytest.raises(RuntimeError, match="readiness"):
            xray_restart.restart(config)
    assert calls[-1] == ["systemctl", "restart", config["target_service"]]
    assert sum(call[:2] == ["systemctl", "restart"] for call in calls) == 1
