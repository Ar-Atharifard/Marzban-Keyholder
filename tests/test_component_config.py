import json
from pathlib import Path
from typing import Any

import pytest

from scripts import backhaul_guard, component_config, forward_config


def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: dict[str, Any]) -> Path:
    path = tmp_path / "components.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    monkeypatch.setenv("KEYHOLDER_COMPONENT_CONFIG", str(path))
    component_config.document.cache_clear()
    return path


def test_configurable_recovery_threshold_preserves_alternate_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(
        tmp_path, monkeypatch, {"backhaul_guard": {"failure_threshold": 2, "cooldown_seconds": 60}}
    )
    state, restart = backhaul_guard.advance({"rathole": "DOWN", "frp": "UP"}, {}, 100, True)
    assert not restart
    _, restart = backhaul_guard.advance({"rathole": "DOWN", "frp": "UP"}, state, 120, True)
    assert restart
    _, restart = backhaul_guard.advance({"rathole": "DOWN", "frp": "DOWN"}, state, 120, True)
    assert not restart


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "3", float("nan")])
def test_invalid_threshold_cannot_run_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    configure(tmp_path, monkeypatch, {"backhaul_guard": {"failure_threshold": value}})
    with pytest.raises(ValueError):
        backhaul_guard.advance({"rathole": "DOWN", "frp": "UP"}, {}, 2000, True)


def test_unknown_fields_and_writable_files_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = configure(tmp_path, monkeypatch, {"backhaul_guard": {"failur_threshold": 1}})
    with pytest.raises(ValueError, match="Unknown"):
        backhaul_guard.advance({}, {}, 1, True)
    path.chmod(0o666)
    component_config.document.cache_clear()
    with pytest.raises(ValueError, match="owner-controlled"):
        backhaul_guard.advance({}, {}, 1, True)


def test_forward_ports_and_keepalives_can_change_without_editing_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(
        tmp_path,
        monkeypatch,
        {"forward": {"server_port": 25000, "client_port": 19000, "keepalive_idle_seconds": 45}},
    )
    server, client = forward_config.configurations(
        "2001:db8::1", "example.org", "id", "private", "public", "short", {"user": "u", "pass": "p"}
    )
    assert server["inbounds"][0]["port"] == 25000
    assert client["inbounds"][0]["port"] == 19000
    assert client["outbounds"][0]["settings"]["vnext"][0]["port"] == 25000
    assert server["inbounds"][0]["streamSettings"]["sockopt"]["tcpKeepAliveIdle"] == 45
    assert server["outbounds"][0]["settings"]["servers"][0]["users"] == [{"user": "u", "pass": "p"}]


def test_preflight_rejects_unknown_fields_before_helper_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = configure(tmp_path, monkeypatch, {"domestic_guard": {"typo_lease_seconds": 10}})
    with pytest.raises(ValueError, match="Unknown"):
        component_config.validate_file(str(path))


@pytest.mark.parametrize("endpoint", ["http://public.example", "https://user:password@example.org"])
def test_credential_endpoint_override_cannot_leak_over_plaintext_or_url_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    configure(tmp_path, monkeypatch, {"management_bot": {"telegram_api_base": endpoint}})
    with pytest.raises(ValueError, match="Credential API"):
        component_config.settings(
            "management_bot", {"telegram_api_base": "https://api.telegram.org"}
        )


def test_alert_endpoint_rejects_plaintext_before_sending_credentials() -> None:
    from scripts import monitor

    with pytest.raises(ValueError, match="HTTPS"):
        monitor.telegram(
            {
                "KEYHOLDER_ALERT_BOT_TOKEN": "synthetic",
                "KEYHOLDER_ALERT_CHAT_ID": "test",
                "KEYHOLDER_ALERT_API_BASE": "http://public.example",
            },
            "test",
        )
    with pytest.raises(ValueError, match="timeout"):
        monitor.request_timeout({"TEST_TIMEOUT": "nan"}, "TEST_TIMEOUT")
