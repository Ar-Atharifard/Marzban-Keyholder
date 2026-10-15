from typing import Any

import pytest

from scripts import management_bot


def test_create_uses_allowlisted_dispatch_and_redacts_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        calls.append((operation, args))
        return {
            "customer": {"id": "customer-id", "name": args["name"]},
            "token": "must-not-appear",
            "subscription_url": "https://example.invalid/s/must-not-appear",
        }

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    state: dict[str, Any] = {}
    output = management_bot.command(
        '/create opaque quota=10 days=30 protocols=vless,trojan name="Full Name"', state
    )
    assert calls[0][0] == "user-create"
    assert calls[0][1]["protocols"] == ["vless", "trojan"]
    assert calls[0][1]["name"] == "Full Name"
    assert "must-not-appear" not in output
    assert "customer-id" in output


def test_destructive_command_requires_matching_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> dict[str, str]:
        calls.append((operation, args))
        return {"status": "revoked"}

    monkeypatch.setattr(
        management_bot,
        "dispatch",
        dispatch,
    )
    state: dict[str, Any] = {}
    prompt = management_bot.command("/revoke alice", state)
    assert calls == []
    code = prompt.rsplit(" ", 1)[1]
    assert "revoked" in management_bot.command("/confirm " + code, state)
    assert calls == [("revoke", {"customer": "alice", "confirmed": True})]


def test_management_help_does_not_offer_subscription_links() -> None:
    text = management_bot.help_text()
    assert "/link" not in text
    assert "SSH CLI" in text


def test_management_daily_inspection_and_identity_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> dict[str, bool]:
        calls.append((operation, args))
        return {"ok": True}

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    state: dict[str, Any] = {}
    management_bot.command("/alerts", state)
    management_bot.command("/runmonitor", state)
    management_bot.command("/history", state)
    management_bot.command("/check alice", state)
    management_bot.command('/rename alice name="Alice Example"', state)
    assert calls == [
        ("alerts-status", {}),
        ("monitor-run", {}),
        ("list", {"limit": 100, "offset": 0, "history": True}),
        ("check", {"customer": "alice"}),
        ("rename", {"customer": "alice", "name": "Alice Example"}),
    ]


def test_remap_requires_confirmation_and_can_be_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        management_bot,
        "dispatch",
        lambda operation, args: pytest.fail("dispatch must wait for confirmation"),
    )
    state: dict[str, Any] = {}
    assert "Confirm" in management_bot.command("/remap alice username=alice_new", state)
    assert state["pending"]["operation"] == "remap"
    assert management_bot.command("/cancel", state) == "Pending operation cancelled."
    assert "pending" not in state
