import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from keyholder import cli
from scripts.admin import worker
from tests.conftest import ADMIN_KEY


@pytest.fixture
def operator(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        response = client.request(
            method, path, json=body, headers={"Authorization": "Bearer " + ADMIN_KEY}
        )
        if response.status_code >= 400:
            raise worker.OperatorError("API rejected operation.")
        return response.json()

    async def upstream(username: str, profiles: list[str]) -> dict[str, Any]:
        return {"available_profiles": profiles, "missing_profiles": []}

    monkeypatch.setattr(worker, "api", api)
    monkeypatch.setattr(worker, "upstream", upstream)


def test_attach_preflight_duplicate_and_link_preserving_management(
    operator: None, client: TestClient
) -> None:
    result = worker.execute("create", {"username": "alice", "name": "Alice"})
    cid = result["customer"]["id"]
    token = result["token"]
    repeated = worker.execute("create", {"username": "alice", "name": "Duplicate"})
    assert repeated["customer"]["id"] == cid and repeated["token"] == token
    assert worker.execute("show", {"customer": "alice"})["id"] == cid
    operations: list[tuple[str, dict[str, Any]]] = [
        ("rename", {"name": "New name"}),
        ("profiles", {"profiles": ["xhttp_reality"]}),
        ("disable", {}),
        ("enable", {}),
        ("remap", {"username": "replacement"}),
    ]
    for operation, fields in operations:
        output = worker.execute(operation, {"customer": cid, **fields})
        assert output["id"] == cid and "token" not in output
    assert client.get("/s/" + token).status_code == 200
    assert worker.execute("show", {"customer": "replacement"})["id"] == cid


def test_customer_identity_cli_update_and_contact_lookup(operator: None) -> None:
    result = worker.execute(
        "create",
        {
            "username": "alice",
            "name": "Alice",
            "telegram": "@Alice_Handle",
            "phone": "+989121234567",
        },
    )
    cid = result["customer"]["id"]
    assert worker.execute("show", {"customer": "alice_handle"})["id"] == cid
    assert worker.execute("show", {"customer": "+989121234567"})["id"] == cid
    updated = worker.execute(
        "customer-update",
        {
            "customer": cid,
            "name": "Alice Example",
            "clear_telegram": True,
            "clear_phone": True,
        },
    )
    assert updated["name"] == "Alice Example"
    assert updated["telegram"] is None and updated["phone"] is None


def test_user_create_accepts_private_identity_fields() -> None:
    args = cli.parser().parse_args(
        [
            "user",
            "create",
            "opaque_01",
            "--name",
            "Full Name",
            "--telegram",
            "@handle",
            "--phone",
            "+989121234567",
            "--quota-gb",
            "10",
            "--days",
            "30",
            "--protocols",
            "vless",
        ]
    )
    assert args.name == "Full Name"
    assert args.telegram == "@handle"
    assert args.phone == "+989121234567"


def test_human_customer_list_starts_with_upstream_username_and_ends_with_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.display(
        [
            {
                "id": "customer-id",
                "name": "Full Name",
                "telegram": "@handle",
                "phone": "+989121234567",
                "status": "active",
                "mapping": {"upstream_username": "panel_user"},
            }
        ],
        as_json=False,
    )
    assert capsys.readouterr().out.rstrip("\n").split("\t") == [
        "panel_user",
        "customer-id",
        "@handle",
        "+989121234567",
        "active",
        "Full Name",
    ]


def test_missing_upstream_profiles_never_creates_customer(
    operator: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def incomplete(username: str, profiles: list[str]) -> dict[str, Any]:
        return {"available_profiles": [], "missing_profiles": profiles}

    monkeypatch.setattr(worker, "upstream", incomplete)
    with pytest.raises(worker.OperatorError, match="missing"):
        worker.execute("create", {"username": "alice", "name": "Alice"})
    assert worker.execute("list", {"limit": 100, "offset": 0}) == []


@pytest.mark.parametrize("operation", ["revoke", "rotate-token"])
def test_worker_requires_confirmation_for_terminal_or_link_breaking_operation(
    operator: None, operation: str
) -> None:
    worker.execute("create", {"username": "alice", "name": "Alice"})
    with pytest.raises(worker.OperatorError, match="confirmation"):
        worker.execute(operation, {"customer": "alice"})
    assert worker.execute("show", {"customer": "alice"})["status"] == "active"


def test_cli_refuses_secret_output_into_logs_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        cli.main(["create", "alice"])
    with pytest.raises(SystemExit):
        cli.main(["rotate-token", "alice", "--confirm"])


def test_cli_private_link_file_and_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = 0
    secret = "https://subscription.example/s/" + "synthetic-secret"

    def request(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True, "result": {"customer": {"id": "fixture"}, "subscription_url": secret}}

    monkeypatch.setattr(cli, "request", request)
    destination = tmp_path / "link.json"
    assert cli.main(["create", "alice", "--save-link", str(destination)]) == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    assert json.loads(destination.read_text())["subscription_url"] == secret
    assert secret not in capsys.readouterr().out
    assert cli.main(["create", "alice", "--save-link", str(destination)]) == 1
    assert calls == 1


def test_failed_cli_request_removes_empty_reserved_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise cli.CLIError("Operation failed; check state before retrying.")

    monkeypatch.setattr(cli, "request", fail)
    path = tmp_path / "link.json"
    assert cli.main(["create", "alice", "--save-link", str(path)]) == 1
    assert not path.exists()


def test_cli_rejects_ssh_option_injection() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--host=-oProxyCommand=bad", "status"])


def test_private_operator_config_can_select_ssh_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ssh = tmp_path / "config"
    ssh.write_text("Host test\n  HostName example.invalid\n")
    operator = tmp_path / "admin.json"
    operator.write_text(json.dumps({"ssh_config": str(ssh)}))
    monkeypatch.setenv("KEYHOLDER_ADMIN_CONFIG", str(operator))
    assert cli.ssh_command() == ["ssh", "-F", str(ssh)]


def test_alert_configuration_requires_interactive_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: pytest.fail("request called"))
    with pytest.raises(SystemExit):
        cli.main(["alerts-configure"])


def test_help_command_is_local_complete_and_supports_subcommands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: pytest.fail("request called"))
    assert cli.main(["help"]) == 0
    overview = capsys.readouterr().out
    for resource in ["user", "customer", "monitor", "heartbeat", "management-bot", "panel"]:
        assert resource in overview
    assert cli.main(["help", "user", "inbounds"]) == 0
    detail = capsys.readouterr().out
    assert "--protocol" in detail and "--tags" in detail


def test_legacy_flat_commands_translate_to_canonical_contract() -> None:
    assert cli.normalize_argv(["management-bot-configure"]) == [
        "management-bot",
        "configure",
    ]
    assert cli.normalize_argv(["--host", "braavos", "link", "alice"]) == [
        "--host",
        "braavos",
        "customer",
        "link",
        "alice",
    ]
    assert cli.normalize_argv(["help", "user-create"]) == ["help", "user", "create"]


def test_panel_bookmark_is_not_printed_to_noninteractive_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        cli.main(["panel-url"])


def test_panel_bookmark_saved_explicitly_without_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "https://edge.example/manage/synthetic-private-bookmark"

    def request(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "result": {"panel_url": url, "active": False}}

    monkeypatch.setattr(cli, "request", request)
    path = tmp_path / "bookmark.json"
    assert cli.main(["panel-url", "--save-link", str(path)]) == 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {"panel_url": url, "active": False}
    assert url not in capsys.readouterr().out


def test_usage_link_reuses_existing_identity_and_stays_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def request(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["operation"] == "link"
        assert payload["args"]["customer"] == "alice"
        assert payload["args"]["backend_id"] == "marzban-default"
        assert "info" not in payload["args"]
        return {
            "result": {
                "customer": {"id": "existing"},
                "subscription_url": "https://sub.example/s/synthetic",
            }
        }

    monkeypatch.setattr(cli, "request", request)
    path = tmp_path / "usage.json"
    assert cli.main(["link", "alice", "--info", "--save-link", str(path)]) == 0
    data = json.loads(path.read_text())
    assert data["usage_url"] == data["subscription_url"] + "?format=info"
    assert data["customer_id"] == "existing"
    assert "synthetic" not in capsys.readouterr().out
    assert path.stat().st_mode & 0o777 == 0o600
