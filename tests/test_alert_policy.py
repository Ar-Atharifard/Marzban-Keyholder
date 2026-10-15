import time
from pathlib import Path
from typing import Any

import pytest

from scripts import monitor


@pytest.fixture
def policy(tmp_path: Path) -> dict[str, Any]:
    file = tmp_path / "monitor.json"
    file.write_text("{}")
    file.chmod(0o600)
    config = monitor.load_config(file)
    config.update(
        state_file=str(tmp_path / "state.json"), secrets_file=str(tmp_path / "absent.env")
    )
    return config


def state_with_alert(policy: dict[str, Any], message: str = "Used 80% (threshold 80%)") -> str:
    key = "user:1:quota"
    incidents, _ = monitor.incident_views(
        {key: message}, {}, {"acks": {}, "silences": {}, "disabled_rules": []}, 1
    )
    monitor.save_state(Path(policy["state_file"]), {"incidents": incidents})
    return key


def test_ack_is_incident_scoped_and_escalation_rearms(policy: dict[str, Any]) -> None:
    key = state_with_alert(policy)
    monitor.control_alerts(policy, "ack", key, 24, False)
    controls = monitor.load_controls(Path(policy["state_file"]))
    previous = monitor.load_state(Path(policy["state_file"]))
    incidents, suppressed = monitor.incident_views(
        {key: "Used 83% (threshold 80%)"}, previous, controls, 2
    )
    assert suppressed == {key}
    escalated, suppressed = monitor.incident_views(
        {key: "Used 95% (threshold 95%)"}, previous, controls, 3
    )
    assert not suppressed
    assert escalated[key]["id"] != incidents[key]["id"]
    reappeared, suppressed = monitor.incident_views(
        {key: "Used 80% (threshold 80%)"}, {}, controls, 4
    )
    assert not suppressed and reappeared[key]["id"] != incidents[key]["id"]


def test_silence_expiry_and_rule_confirmation(
    policy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    key = state_with_alert(policy)
    monkeypatch.setattr(time, "time", lambda: 100)
    monitor.control_alerts(policy, "silence", key, 1, False)
    controls = monitor.load_controls(Path(policy["state_file"]))
    previous = monitor.load_state(Path(policy["state_file"]))
    assert monitor.incident_views({key: "threshold 80%"}, previous, controls, 101)[1] == {key}
    assert not monitor.incident_views({key: "threshold 80%"}, previous, controls, 3701)[1]
    with pytest.raises(ValueError, match="confirmation"):
        monitor.control_alerts(policy, "rule-disable", "user.quota", 24, False)
    monitor.control_alerts(policy, "rule-disable", "user.quota", 24, True)
    assert monitor.control_alerts(policy, "list", "", 24, False)["controls"]["disabled_rules"] == [
        "user.quota"
    ]
    monitor.control_alerts(policy, "rule-enable", "user.quota", 24, False)
    assert monitor.control_alerts(policy, "list", "", 24, False)["controls"]["disabled_rules"] == []
    monitor.control_alerts(policy, "unsilence", key, 24, False)
    assert monitor.load_controls(Path(policy["state_file"]))["silences"] == {}


@pytest.mark.parametrize("hours", [0, -1, 169, float("nan"), float("inf")])
def test_silence_rejects_invalid_durations(policy: dict[str, Any], hours: float) -> None:
    key = state_with_alert(policy)
    with pytest.raises(ValueError):
        monitor.control_alerts(policy, "silence", key, hours, False)


@pytest.mark.parametrize(
    "action,target",
    [("ack", "missing"), ("silence", "missing"), ("rule-disable", "made.up"), ("bogus", "x")],
)
def test_controls_reject_invalid_targets(policy: dict[str, Any], action: str, target: str) -> None:
    with pytest.raises(ValueError):
        monitor.control_alerts(policy, action, target, 24, True)


def test_delivery_dedup_failure_retry_and_recovery(
    policy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    active = {"user:1:quota": "Used 80.1% (threshold 80%)"}
    monkeypatch.setattr(monitor, "container_alerts", lambda _: {})
    monkeypatch.setattr(monitor, "systemd_alerts", lambda _: {})
    monkeypatch.setattr(monitor, "resource_alerts", lambda _: {})
    monkeypatch.setattr(monitor, "network_alerts", lambda _: {})
    monkeypatch.setattr(monitor, "backup_alerts", lambda *_: {})
    monkeypatch.setattr(monitor, "user_alerts", lambda *_: (dict(active), {}))
    monkeypatch.setattr(
        monitor, "system_metrics", lambda: {"cpu_total_ticks": 1, "cpu_idle_ticks": 1}
    )
    monkeypatch.setattr(monitor, "heartbeat", lambda _: None)
    sent: list[str] = []

    def send(env: dict[str, str], text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(monitor, "telegram", send)
    monitor.run(policy)
    active["user:1:quota"] = "Used 84% (threshold 80%)"
    monitor.run(policy)
    assert len(sent) == 1
    active["user:1:quota"] = "Used 96% (threshold 95%)"
    monitor.run(policy)
    assert len(sent) == 2
    monitor.control_alerts(policy, "ack", "user:1:quota", 24, False)
    monitor.run(policy)
    assert len(sent) == 2
    active.clear()
    monitor.run(policy)
    assert len(sent) == 3 and "RECOVERED" in sent[-1]
    active["user:1:quota"] = "Used 96% (threshold 95%)"

    def fail(*args: object) -> bool:
        raise TimeoutError()

    monkeypatch.setattr(monitor, "telegram", fail)
    result = monitor.run(policy)
    assert result["notification_error"] == "TimeoutError"
    assert not result["notified_alerts"]
    monkeypatch.setattr(monitor, "telegram", send)
    monitor.run(policy)
    assert len(sent) == 4


def test_rule_registry_covers_expected_keys() -> None:
    for key in [
        "user:1:quota",
        "user:2:account",
        "disk:critical",
        "inode:warning",
        "memory:available",
        "swap:used",
        "cpu:load",
        "container:x",
        "systemd:x",
        "http:x",
        "tcp:x",
        "backup:age",
        "marzban:usage",
        "marzban:users",
    ]:
        assert monitor.rule_for_key(key) in monitor.RULES
    assert monitor.severity_for_key("disk:critical") == "critical"


def test_disabled_rule_keeps_health_and_active_incidents_visible(
    policy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    active = {"http:public": "unreachable"}
    for function in ["container_alerts", "systemd_alerts", "resource_alerts", "network_alerts"]:
        monkeypatch.setattr(monitor, function, lambda *_: {})
    monkeypatch.setattr(monitor, "network_alerts", lambda *_: active)
    monkeypatch.setattr(monitor, "backup_alerts", lambda *_: {})
    monkeypatch.setattr(monitor, "user_alerts", lambda *_: ({}, {}))
    monkeypatch.setattr(
        monitor, "system_metrics", lambda: {"cpu_total_ticks": 1, "cpu_idle_ticks": 1}
    )
    monitor.control_alerts(policy, "rule-disable", "service.http", 24, True)
    monkeypatch.setattr(monitor, "telegram", lambda *_: pytest.fail("disabled notification sent"))
    monkeypatch.setattr(
        monitor, "heartbeat", lambda *_: pytest.fail("unhealthy infrastructure pinged")
    )
    result = monitor.run(policy)
    assert not result["healthy"]
    assert result["incidents"]["http:public"]["notification_state"] == "rule_disabled"
    assert result["alerts"] == active
