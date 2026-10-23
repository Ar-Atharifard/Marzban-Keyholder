import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import monitor, proxy_probe


def test_client_config_keeps_credentials_out_of_listener_and_routes_each_profile() -> None:
    profiles: list[dict[str, Any]] = [
        {
            "remarks": "first",
            "outbounds": [{"protocol": "vless", "settings": {"secret": "private"}}],
        },
        {"remarks": "second", "outbounds": [{"protocol": "trojan", "settings": {}}]},
    ]
    config, ports = proxy_probe.client_config(profiles)
    assert len(set(ports)) == 2
    assert all(i["listen"] == "127.0.0.1" for i in config["inbounds"])
    assert config["routing"]["rules"][1]["outboundTag"] == "probe-1"
    assert profiles[0]["outbounds"][0].get("tag") is None
    assert "private" not in json.dumps(config["inbounds"])


@pytest.mark.parametrize("profiles", [[], [{}] * 129])
def test_invalid_profile_count(profiles: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        proxy_probe.client_config(profiles)


def test_destination_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [subprocess.CompletedProcess([], 28, "000"), subprocess.CompletedProcess([], 0, "204")]
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: next(results))
    assert proxy_probe.check(1234)["healthy"]


def test_failed_destinations_do_not_leak_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 35, "000", "private credential"),
    )
    result = proxy_probe.check(1234)
    assert not result["healthy"]
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "failures,healthy,expected",
    [(1, False, False), (2, False, True), (10, False, True), (0, True, False)],
)
def test_alert_requires_two_failed_runs(
    tmp_path: Path, failures: int, healthy: bool, expected: bool
) -> None:
    path = tmp_path / "proxy.json"
    now = dt.datetime.now(dt.UTC)
    path.write_text(
        json.dumps(
            {
                "checked_at": now.isoformat(),
                "profiles": {
                    "profile a": {"healthy": healthy, "failures": failures},
                    "profile b": {"healthy": healthy, "failures": failures},
                },
            }
        )
    )
    alerts = monitor.proxy_alerts({"proxy_status_file": str(path)}, now.timestamp())
    assert bool(alerts) == expected
    assert len(alerts) <= 1
    if alerts:
        assert monitor.rule_for_key(next(iter(alerts))) == "service.proxy"
        assert monitor.severity_for_key(next(iter(alerts))) == "critical"


def test_stale_and_missing_probe_report_alert(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    config = {"proxy_status_file": str(path)}
    assert "proxy:monitor" in monitor.proxy_alerts(config, 1000)
    path.write_text(json.dumps({"checked_at": "1970-01-01T00:00:00+00:00", "profiles": {}}))
    assert "proxy:monitor" in monitor.proxy_alerts(config, 1000)
    assert not monitor.proxy_alerts({}, 1000)


def test_probe_setup_error_is_not_a_profile_outage(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    now = dt.datetime.now(dt.UTC)
    path.write_text(
        json.dumps({"checked_at": now.isoformat(), "error": "ValueError", "failures": 2})
    )
    assert set(monitor.proxy_alerts({"proxy_status_file": str(path)}, now.timestamp())) == {
        "proxy:monitor"
    }


def test_tls_negotiation_groups_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    batches = []

    def run_group(
        profiles: list[dict[str, Any]], binary: Path, domestic_prefix: str = ""
    ) -> dict[str, dict[str, Any]]:
        batches.append(profiles)
        return {p["remarks"]: {"healthy": True} for p in profiles}

    monkeypatch.setattr(proxy_probe, "_probe_group", run_group)
    profiles = [
        {
            "remarks": str(index),
            "outbounds": [{"streamSettings": {"security": "tls", "tlsSettings": {"alpn": alpn}}}],
        }
        for index, alpn in enumerate([["h2"], ["http/1.1"], ["h2"]])
    ]
    assert set(proxy_probe.probe(profiles, Path("unused"))) == {"0", "1", "2"}
    assert [len(batch) for batch in batches] == [2, 1]


@pytest.mark.parametrize("foreign,local", [(True, True), (False, True), (True, False)])
def test_domestic_probe_checks_filtered_foreign_and_domestic_destinations(
    monkeypatch: pytest.MonkeyPatch, foreign: bool, local: bool
) -> None:
    answers = iter([True, foreign, local])
    calls = []

    def check(port: int, *urls: tuple[str, ...]) -> dict[str, Any]:
        calls.append(urls)
        return {"healthy": next(answers)}

    monkeypatch.setattr(proxy_probe, "check", check)
    monkeypatch.setattr(proxy_probe, "udp_check", lambda port: True)
    result = proxy_probe.check_entry(1234, True)
    assert result["healthy"] == (foreign and local)
    assert result["policy_checks"] == {"foreign": foreign, "domestic": local, "udp": True}
    assert "youtube" in calls[1][0][0]
    assert "aparat" in calls[2][0][0]


def test_configured_domestic_profile_cannot_disappear_silently() -> None:
    with pytest.raises(ValueError, match="missing"):
        proxy_probe.probe([{"remarks": "foreign"}], Path("unused"), "IR | ")


def test_domestic_udp_cannot_fail_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proxy_probe, "check", lambda *args: {"healthy": True})
    monkeypatch.setattr(proxy_probe, "udp_check", lambda port: False)
    assert not proxy_probe.check_entry(1234, True)["healthy"]


def test_udp_canary_uses_only_loopback_and_matching_profile() -> None:
    config, ports = proxy_probe.client_config(
        [{"remarks": "IR | test", "outbounds": [{"protocol": "vless", "settings": {}}]}], "IR | "
    )
    udp = next(i for i in config["inbounds"] if i["protocol"] == "dokodemo-door")
    assert udp["listen"] == "127.0.0.1" and udp["port"] == ports[0]
    assert config["routing"]["rules"][-1]["outboundTag"] == "probe-0"


@pytest.mark.parametrize("healthy", [True, False])
def test_probe_journal_retains_safe_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    healthy: bool,
) -> None:
    monkeypatch.setattr("sys.argv", ["probe", "--state", str(tmp_path / "proxy.json")])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, '{"private": "credential"}'),
    )
    monkeypatch.setattr(
        proxy_probe,
        "probe",
        lambda *a: {
            "example profile": {
                "healthy": healthy,
                "reason": "Policy check failed",
                "policy_checks": {"foreign": True, "udp": healthy},
                "unexpected_private_field": "credential",
            },
        },
    )
    assert proxy_probe.main() == (0 if healthy else 1)
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert "credential" not in output
    assert summary["failed"] == (
        {}
        if healthy
        else {
            "example profile": {
                "reason": "Policy check failed",
                "policy_checks": {"foreign": True, "udp": False},
            },
        }
    )
