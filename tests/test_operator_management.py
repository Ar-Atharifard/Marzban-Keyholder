import sys
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from keyholder.cli import main, parser


def test_management_commands_cover_provisioning_and_panel_selection() -> None:
    args = parser().parse_args(
        [
            "user",
            "create",
            "alice",
            "--quota-gb",
            "20",
            "--days",
            "30",
            "--protocols",
            "vless",
            "trojan",
        ]
    )
    assert args.quota_gb == 20 and args.days == 30
    args = parser().parse_args(
        [
            "user",
            "inbounds",
            "alice",
            "--protocol",
            "trojan",
            "--tags",
            "TROJAN GRPC CDN TITAN",
        ]
    )
    assert args.tags == ["TROJAN GRPC CDN TITAN"]
    assert parser().parse_args(["user", "usage", "alice"]).username == "alice"
    assert parser().parse_args(["user", "reset-usage", "alice", "--confirm"]).confirmed
    for op in ["users", "inbounds", "sync"]:
        assert parser().parse_args(["upstream", op]).operation == op


@pytest.mark.parametrize(
    "command",
    [
        ["link", "alice"],
        ["reconcile"],
        ["user-reset-usage", "alice"],
        ["user-update", "alice"],
        ["user-create", "alice", "--quota-gb", "-1", "--days", "30", "--protocols", "vless"],
        ["user-create", "alice", "--quota-gb", "nan", "--days", "30", "--protocols", "vless"],
    ],
)
def test_invalid_or_secret_management_request_never_reaches_server(
    command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        main(command)


def test_doctor_verifies_registry_and_vault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.admin import worker
    from tests.conftest import ADMIN_KEY
    from tests.test_api import create

    create(client)
    app = cast(FastAPI, client.app)
    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("KEYHOLDER_DATABASE_URL", str(app.state.settings.database_url))
    monkeypatch.setenv(
        "KEYHOLDER_TOKEN_ENCRYPTION_KEY", app.state.settings.token_encryption_key.get_secret_value()
    )
    # Test fixture schema is made directly; install the migration revision metadata only.
    from sqlalchemy import text

    with app.state.engine.begin() as db:
        db.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
        db.execute(text("INSERT INTO alembic_version VALUES ('0003')"))

    async def inventory(operation: str, args: dict[str, Any]) -> list[dict[str, str]]:
        return [{"username": "alice"}]

    monkeypatch.setattr(worker, "panel_operation", inventory)
    result = worker.execute("doctor", {})
    assert result["healthy"] is True
    assert result["canonical_registrations"] == result["retrievable_links"] == 1
    assert "token" not in str(result) and "subscription_url" not in str(result)


@pytest.mark.parametrize("tags", [["NEW"], []])
def test_panel_selection_preserves_credentials_and_accepts_empty_selection(
    monkeypatch: pytest.MonkeyPatch, tags: list[str]
) -> None:
    import asyncio
    import copy

    import httpx

    from keyholder.backends.marzban import MarzbanBackend
    from scripts.admin import worker
    from tests.conftest import ADMIN_KEY

    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", ADMIN_KEY)
    user: dict[str, Any] = {
        "username": "alice",
        "status": "active",
        "data_limit": 123,
        "expire": 456,
        "proxies": {"vless": {"id": "synthetic-id"}, "trojan": {"password": "synthetic-password"}},
        "inbounds": {"vless": ["OLD"], "trojan": ["PREVIOUS"]},
    }
    submitted: list[dict[str, Any]] = []

    async def login(self: MarzbanBackend) -> None:
        self.token = "synthetic"

    async def request(
        self: MarzbanBackend, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if path == "/api/inbounds":
            return httpx.Response(200, json={"trojan": [{"tag": "NEW"}]})
        if method == "GET":
            return httpx.Response(200, json=copy.deepcopy(user))
        submitted.append(kwargs["json"])
        return httpx.Response(200, json={**user, **kwargs["json"]})

    monkeypatch.setattr(MarzbanBackend, "login", login)
    monkeypatch.setattr(MarzbanBackend, "request", request)
    result = asyncio.run(
        worker.panel_operation(
            "user-inbounds",
            {
                "username": "alice",
                "protocol": "trojan",
                "tags": tags,
            },
        )
    )
    assert submitted == [{"inbounds": {"vless": ["OLD"], "trojan": tags}}]
    assert result["data_limit"] == 123 and result["expire"] == 456
    assert "synthetic-password" not in str(result)


def test_doctor_failed_health_has_nonzero_cli_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    from keyholder import cli

    monkeypatch.setattr(cli, "request", lambda *a, **kw: {"ok": True, "result": {"healthy": False}})
    assert main(["doctor"]) == 1


def test_reset_usage_requires_confirmation_inside_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from keyholder.backends.marzban import MarzbanBackend
    from scripts.admin import worker
    from tests.conftest import ADMIN_KEY

    monkeypatch.setenv("KEYHOLDER_ADMIN_KEY", ADMIN_KEY)

    async def login(self: MarzbanBackend) -> None:
        self.token = "synthetic"

    monkeypatch.setattr(MarzbanBackend, "login", login)
    with pytest.raises(worker.OperatorError, match="requires --confirm"):
        asyncio.run(worker.panel_operation("user-reset-usage", {"username": "alice"}))


@pytest.mark.parametrize("count", [0, 2])
def test_lookup_distinguishes_missing_registration_from_duplicates(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    from scripts.admin import worker

    monkeypatch.setattr(
        worker,
        "customers",
        lambda: [
            {
                "mapping": {"upstream_username": "ALICE", "backend_id": "marzban-default"},
                "status": "active",
            }
            for _ in range(count)
        ],
    )
    expected = "No Keyholder registration" if count == 0 else "selector is ambiguous"
    with pytest.raises(worker.OperatorError, match=expected):
        worker.resolve("ALICE")
