import json
import subprocess
from typing import Any

import pytest

from scripts import monitor


def snapshot() -> dict[str, Any]:
    return {
        "metrics": {
            "disk_used_gib": 10,
            "disk_total_gib": 30,
            "memory_available_mib": 1000,
            "cpus": 2,
            "load_1_5_15": [0, 0, 0],
        },
        "services": {"node": "active"},
        "guard": {"entry_permitted": True},
    }


def test_remote_health_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    data = snapshot()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, json.dumps(data)),
    )
    alerts, metrics = monitor.remote_hosts(
        [{"name": "gate", "ssh_config": "private", "target": "gate"}]
    )
    assert alerts == {}
    assert metrics == {"gate": data}


def test_remote_service_and_resources_alert_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = snapshot()
    data["services"]["node"] = "failed"
    data["metrics"].update(disk_used_gib=29, memory_available_mib=100, load_1_5_15=[4, 4, 4])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, json.dumps(data)),
    )
    alerts, _ = monitor.remote_hosts([{"name": "gate", "ssh_config": "private", "target": "gate"}])
    assert set(alerts) == {
        "remote:gate:service",
        "remote:gate:disk",
        "remote:gate:memory",
        "remote:gate:cpu",
    }
    assert monitor.rule_for_key("remote:gate:service") == "service.remote"
    assert monitor.severity_for_key("remote:gate:service") == "critical"


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        "{}",
        "[]",
        "x" * 65537,
        json.dumps({"metrics": {}, "services": [], "guard": {"entry_permitted": True}}),
        json.dumps({**snapshot(), "guard": {"entry_permitted": "false"}}),
        json.dumps({**snapshot(), "metrics": {**snapshot()["metrics"], "load_1_5_15": []}}),
    ],
)
def test_invalid_remote_reply_becomes_one_incident(
    monkeypatch: pytest.MonkeyPatch, output: Any
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, output)
    )
    alerts, metrics = monitor.remote_hosts(
        [{"name": "gate", "ssh_config": "private", "target": "gate"}]
    )
    assert metrics == {}
    assert alerts == {"remote:gate:unavailable": "gate: telemetry unavailable"}


def test_remote_timeout_does_not_expose_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired("private command", 10)

    monkeypatch.setattr(subprocess, "run", fail)
    alerts, _ = monitor.remote_hosts([{"name": "gate", "ssh_config": "private", "target": "gate"}])
    assert "private" not in json.dumps(alerts)


@pytest.mark.parametrize(
    ("paths", "incident"),
    [
        ({"rathole": "UP", "frp": "UP"}, None),
        ({"rathole": "DOWN", "frp": "UP"}, "redundancy"),
        ({"rathole": "UP", "frp": "DOWN"}, "redundancy"),
        ({"rathole": "DOWN", "frp": "DOWN"}, "backhaul"),
        ({}, "backhaul"),
    ],
)
def test_backhaul_health_distinguishes_outage_and_redundancy(
    monkeypatch: pytest.MonkeyPatch, paths: dict[str, str], incident: str | None
) -> None:
    data = {**snapshot(), "backhauls": paths}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, json.dumps(data))
    )
    alerts, _ = monitor.remote_hosts([{"name": "gate", "ssh_config": "private", "target": "gate"}])
    expected = set() if incident is None else {"remote:gate:" + incident}
    assert set(alerts) == expected
    if incident:
        assert monitor.severity_for_key("remote:gate:" + incident) == (
            "critical" if incident == "backhaul" else "warning"
        )
