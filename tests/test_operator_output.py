import json
from typing import Any

import pytest

from keyholder import cli
from keyholder.operator_output import render


def test_nested_telemetry_has_units_dates_and_copyable_incident_keys() -> None:
    text = render(
        {
            "metrics": {
                "memory_available_mib": 123.5,
                "received_bytes": 5 * 1024**3,
                "uptime_seconds": 90061,
                "cpu_busy_percent": 98.5,
                "load_1_5_15": [2.34, 1.23, 0.5],
                "cpu_total_ticks": 123456789,
            },
            "incidents": {
                "user:12:quota": {
                    "notification_state": "automatic_silence",
                    "first_seen": 1767225600,
                    "message": "User alice has used 95% of quota",
                    "signature": "internal",
                    "guidance": "Review quota in Marzban.",
                }
            },
            "controls": {"silences": {"user:12:quota": 1767225600}},
        }
    )
    for expected in (
        "Available RAM: 123.50 MiB",
        "Network received: 5.00 GiB",
        "Uptime: 1 day 1 hour 1 minute 1 second",
        "CPU busy: 98.50%",
        "2.34 / 1.23 / 0.50",
        "user:12:quota:",
        "automatic silence",
        "2026-01-01 00:00:00 UTC",
        "Next step: Review quota in Marzban.",
    ):
        assert expected in text
    assert "123456789" not in text and "Signature" not in text


def test_missing_quota_in_per_node_usage_does_not_imply_unlimited() -> None:
    text = render(
        {
            "username": "alice",
            "usages": [
                {"node_id": 1234, "node_name": "Gate", "used_traffic": 3 * 1024**3},
                {"node_id": None, "node_name": "Master", "used_traffic": 1024},
            ],
        }
    )
    assert "Unlimited" not in text and "Remaining quota" not in text
    assert "3.00 GiB" in text and "1.00 KiB" in text
    assert "Node ID: 1234" in text
    assert "Node ID: Not available" in text


def test_money_preserves_decimal_precision_and_identifiers_and_redacts_secrets() -> None:
    text = render(
        {
            "customer_id": "copy_me_exactly",
            "balances": {
                "IRR": {"outstanding": "1000000", "unallocated": "2000"},
                "USDT": {"outstanding": "0.000001"},
            },
            "receipt": {"id": "receipt-id", "size_bytes": 2048, "media_type": "image/png"},
            "created_at": "2026-01-01T03:30:00+03:30",
            "nested": {
                "token": "private-token",
                "config_uri": "vless://private",
                "content": "private-image",
            },
        }
    )
    assert "copy_me_exactly" in text
    assert "1,000,000 IRR" in text and "0.000001 USDT" in text
    assert "2.00 KiB" in text and "2026-01-01 00:00:00 UTC" in text
    assert "private" not in text


@pytest.mark.parametrize("as_json", [True, False])
def test_cli_human_output_and_explicit_json_contract(
    capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    value: dict[str, Any] = {"data_limit": 5 * 1024**3, "used_traffic": 1024, "expire": 0}
    cli.display(value, as_json)
    text = capsys.readouterr().out
    if as_json:
        assert json.loads(text) == value
    else:
        assert "Traffic allowance: 5.00 GiB" in text
        assert "Remaining quota:" in text and "Expires: No expiry" in text


def test_expiry_and_on_hold_are_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("keyholder.operator_output.time.time", lambda: 1767225600)
    assert "Time remaining: 1 hour 1 minute" in render({"expire": 1767229260})
    assert "Time remaining: Expired" in render({"expire": 1767225599})
    assert "Awaiting activation" in render({"status": "on_hold", "expire": 0})
    assert "Expires: Not available" in render({"expire": None})
