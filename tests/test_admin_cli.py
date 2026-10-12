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
