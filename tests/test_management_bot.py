from typing import Any

import pytest

from scripts import management_bot


def test_directory_only_returns_names_and_usernames(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        calls.append((operation, args))
        return [{"username": "alice", "name": "Alice Example"}]

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    assert management_bot.command('/directory 2 "Alice Example"', {}) == "alice | Alice Example"
    assert calls == [
        ("list", {"limit": 30, "offset": 30, "brief": True, "search": "Alice Example"})
    ]
    management_bot.command('/show "Alice Example"', {})
    assert calls[-1] == ("show", {"customer": "Alice Example"})
    management_bot.command('/customers "Alice Example"', {})
    assert calls[-1] == (
        "list",
        {"limit": 10, "offset": 0, "history": False, "search": "Alice Example"},
    )


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


def test_management_help_lists_explicit_private_link_commands() -> None:
    text = management_bot.help_text()
    assert "/link SELECTOR" in text
    assert "/config SELECTOR CONFIG_ID" in text
    assert "private administrator chat" in text


def test_help_describes_commands_and_distinguishes_global_inbound_list() -> None:
    text = management_bot.help_text()
    assert len(text) <= management_bot.MAX_MESSAGE
    assert "/inbounds — ALL available inbounds" in text
    assert "/inbounds USER — Open that user's selection picker" in text
    assert "omitted means default" in text
    assert "not panel username" in text
    for command in management_bot.BOT_COMMANDS:
        assert "/" + command["command"] in text
    for line in text.splitlines():
        if line.startswith("/"):
            assert " — " in line


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
        ("list", {"limit": 10, "offset": 0, "history": True}),
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


def test_large_replies_are_split_without_losing_content(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def telegram(token: str, method: str, values: dict[str, str]) -> dict[str, Any]:
        sent.append(values["text"])
        return {"ok": True}

    monkeypatch.setattr(management_bot, "telegram", telegram)
    text = "a" * 6000
    management_bot.send_reply("synthetic", 123456789, text)
    assert "".join(sent) == text
    assert all(len(page) <= management_bot.MAX_MESSAGE for page in sent)


def test_customer_inventory_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> list[Any]:
        calls.append(args)
        return []

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    management_bot.command("/customers 2", {})
    assert calls == [{"limit": 10, "offset": 10, "history": False}]


@pytest.mark.parametrize(
    "text,operation,expected",
    [
        ("/status", "status", {}),
        ("/health", "health", {}),
        ("/doctor", "doctor", {}),
        ("/metrics", "system-metrics", {}),
        ("/backends", "backends", {}),
        ("/monitor", "monitor-status", {}),
        ("/runmonitor", "monitor-run", {}),
        ("/alerts", "alerts-status", {}),
        ("/users", "users", {}),
        ("/sync", "sync", {}),
        ("/backup", "backup", {}),
        ("/customers", "list", {"limit": 10, "offset": 0, "history": False}),
        ("/history 2", "list", {"limit": 10, "offset": 10, "history": True}),
        ("/show alice", "show", {"customer": "alice"}),
        ("/check alice", "check", {"customer": "alice"}),
        ("/enable alice", "enable", {"customer": "alice"}),
        ("/disable alice", "disable", {"customer": "alice"}),
        ("/usage alice", "user-usage", {"username": "alice"}),
        (
            "/attach alice",
            "create",
            {
                "username": "alice",
                "name": "alice",
                "telegram": None,
                "phone": None,
                "profiles": None,
            },
        ),
        (
            "/update alice quota=5 days=30 status=active",
            "user-update",
            {"username": "alice", "quota_gb": 5, "days": 30, "status": "active"},
        ),
        (
            "/identity alice telegram= phone=",
            "customer-update",
            {
                "customer": "alice",
                "name": None,
                "telegram": "",
                "phone": "",
                "clear_telegram": True,
                "clear_phone": True,
            },
        ),
        (
            "/setinbounds alice protocol=vless tags=A,B",
            "user-inbounds",
            {"username": "alice", "protocol": "vless", "tags": ["A", "B"]},
        ),
        ('/rename alice name="Full Name"', "rename", {"customer": "alice", "name": "Full Name"}),
        (
            "/ack user:1:quota",
            "monitor-control",
            {"control_action": "ack", "target": "user:1:quota"},
        ),
        (
            "/unack user:1:quota",
            "monitor-control",
            {"control_action": "unack", "target": "user:1:quota"},
        ),
        (
            "/silence user:1:quota hours=2",
            "monitor-control",
            {"control_action": "silence", "target": "user:1:quota", "hours": 2},
        ),
        (
            "/unsilence user:1:quota",
            "monitor-control",
            {"control_action": "unsilence", "target": "user:1:quota"},
        ),
        (
            "/rule_enable user.quota",
            "monitor-control",
            {"control_action": "rule-enable", "target": "user.quota"},
        ),
        ("/alertcontrols", "monitor-control", {"control_action": "list", "target": ""}),
    ],
)
def test_all_regular_command_contracts(
    text: str, operation: str, expected: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(op: str, args: dict[str, Any]) -> dict[str, bool]:
        calls.append((op, args))
        return {"ok": True}

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    management_bot.command(text, {})
    assert calls == [(operation, expected)]


@pytest.mark.parametrize(
    "text",
    [
        "/show",
        "/usage",
        "/enable a b",
        "/customers 0",
        "/customers -1",
        "/history 1 2",
        "/create alice",
        "/create alice quota=nan days=1 protocols=vless",
        "/create alice quota=5 days=1.5 protocols=vless",
        "/create alice quota=5 days=1 protocols=invalid",
        "/create alice quota=5 quota=6 days=1 protocols=vless",
        "/create alice quota=5 days=1 protocols=vless unknown=x",
        "/attach alice unknown=x",
        "/update alice",
        "/update alice days=2.5",
        "/update alice status=broken",
        "/identity alice",
        "/identity alice extra=x",
        "/setinbounds alice protocol=vless",
        "/rename alice name=",
        "/silence user:1:quota hours=nan",
        "/silence user:1:quota hours=0",
        "/silence user:1:quota hours=169",
        "/ack",
        "/ack a b",
        "/ack a hours=1",
        "/alertcontrols extra",
        "/cancel extra",
        "/unknown",
        '/rename alice name="broken',
    ],
)
def test_invalid_commands_do_not_dispatch(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        management_bot, "dispatch", lambda *_: pytest.fail("invalid input dispatched")
    )
    with pytest.raises(ValueError):
        management_bot.command(text, {})


@pytest.mark.parametrize(
    "text,operation",
    [
        ("/revoke alice", "revoke"),
        ("/rotate alice", "rotate-token"),
        ("/resetusage alice", "user-reset-usage"),
        ("/remap alice username=new_user", "remap"),
        ("/rule_disable user.quota", "monitor-control"),
    ],
)
def test_every_confirmation_is_single_use(
    text: str, operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def dispatch(op: str, args: dict[str, Any]) -> dict[str, bool]:
        calls.append(op)
        return {"ok": True}

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    state: dict[str, Any] = {}
    management_bot.command(text, state)
    assert not calls
    code = state["pending"]["code"]
    management_bot.command("/confirm " + code, state)
    assert calls == [operation]
    with pytest.raises(ValueError, match="invalid or expired"):
        management_bot.command("/confirm " + code, state)


def test_expired_confirmation_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        management_bot, "dispatch", lambda *_: pytest.fail("expired confirmation dispatched")
    )
    state: dict[str, Any] = {
        "pending": {"code": "abcdef", "expires": 0, "operation": "revoke", "args": {}}
    }
    with pytest.raises(ValueError, match="expired"):
        management_bot.command("/confirm abcdef", state)


@pytest.mark.parametrize(
    "chat_type,chat_id,sender_id,expected",
    [
        ("private", 123, 123, True),
        ("group", 123, 123, False),
        ("private", 124, 123, False),
        ("private", 123, 124, False),
    ],
)
def test_authorization_requires_private_owner(
    chat_type: str, chat_id: int, sender_id: int, expected: bool
) -> None:
    assert (
        management_bot.authorized(
            {"chat": {"type": chat_type, "id": chat_id}, "from": {"id": sender_id}}, 123
        )
        is expected
    )


def test_missing_authorization_fields_fail_closed() -> None:
    assert not management_bot.authorized({}, 123)


@pytest.mark.parametrize(
    "text",
    [
        "/create alice quota=5 days=1 protocols=vless name=",
        "/create a quota=5 days=1 protocols=vless",
        "/attach bad-name",
        "/identity alice name=",
        "/setinbounds alice protocol=bad tags=",
        "/help " + "x" * 2050,
    ],
)
def test_invalid_identity_and_protocol_never_mutate(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        management_bot, "dispatch", lambda *_: pytest.fail("invalid request dispatched")
    )
    with pytest.raises(ValueError):
        management_bot.command(text, {})


@pytest.mark.parametrize("stdout", ["not-json", '{"ok":false,"error":"safe failure"}'])
def test_dispatch_failure_is_not_success(stdout: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    result = subprocess.CompletedProcess(
        ["dispatcher"], 1, stdout=stdout.encode(), stderr=b"private-secret"
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    with pytest.raises(ValueError) as error:
        management_bot.dispatch("status", {})
    assert "private-secret" not in str(error.value)


def test_nested_secrets_are_redacted() -> None:
    assert management_bot.redact(
        {
            "users": [
                {
                    "name": "Alice",
                    "password": "secret",
                    "token": "secret",
                    "subscription_url": "secret",
                    "panel_url": "secret",
                }
            ]
        }
    ) == {"users": [{"name": "Alice"}]}


def test_telegram_rate_limit_retries_delivery_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import email.message
    import io
    import json
    import time
    import urllib.error
    import urllib.request

    delays: list[float] = []
    calls: list[object] = []

    class Response:
        def __enter__(self: Any) -> object:
            return io.BytesIO(b'{"ok":true,"result":{}}')

        def __exit__(self: Any, *args: object) -> None:
            pass

    class Opener:
        def open(self: Any, request: object, **kwargs: object) -> Response:
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://example.invalid",
                    429,
                    "rate limited",
                    email.message.Message(),
                    io.BytesIO(json.dumps({"parameters": {"retry_after": 2}}).encode()),
                )
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(time, "sleep", delays.append)
    assert management_bot.telegram("synthetic", "sendMessage", {"text": "hello"})["ok"]
    assert len(calls) == 2 and delays == [2.1]


@pytest.mark.parametrize(
    "name,expected", [("link", "https://example.invalid/s/secret"), ("config", "vless://secret")]
)
def test_only_explicit_link_commands_return_requested_credential(
    monkeypatch: pytest.MonkeyPatch, name: str, expected: str
) -> None:
    calls = []

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        calls.append((operation, args))
        return {
            "subscription_url": "https://example.invalid/s/secret",
            "config_uri": "vless://secret",
            "token": "RAW-TOKEN-NEVER-RETURN",
        }

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    text = "/link alice" if name == "link" else "/config alice abc123"
    assert management_bot.command(text, {}) == expected
    assert calls[0][0] == name
    assert management_bot.redact(dispatch("", {})) == {}


def test_link_commands_reject_wrong_arguments_and_oversized_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for text in ["/link", "/link alice extra", "/config alice", "/configs alice extra"]:
        with pytest.raises(ValueError):
            management_bot.command(text, {})
    monkeypatch.setattr(
        management_bot,
        "dispatch",
        lambda *args: {"subscription_url": "x" * (management_bot.MAX_MESSAGE + 1)},
    )
    with pytest.raises(ValueError, match="message size"):
        management_bot.command("/link alice", {})


@pytest.mark.parametrize(
    "used,limit,expected",
    [
        (96 * 1024**3, 100 * 1024**3, "4.00 GiB"),
        (101 * 1024**3, 100 * 1024**3, "0 B"),
        (1024, 0, "Unlimited"),
        (1024, None, "Unlimited"),
    ],
)
def test_usage_display_has_readable_quota(used: int, limit: int | None, expected: str) -> None:
    text = management_bot.readable_result({"used_traffic": used, "data_limit": limit, "expire": 0})
    assert f"Remaining quota: {expected}" in text
    assert "Expire: Unlimited" in text
    assert "Used traffic:" in text
    assert "GiB" in text or "KiB" in text
