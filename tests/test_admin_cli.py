import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scripts.admin import cli, worker
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
    with pytest.raises(worker.OperatorError, match="already attached"):
        worker.execute("create", {"username": "alice", "name": "Duplicate"})
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
