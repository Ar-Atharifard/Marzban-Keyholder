import sys

import pytest

from scripts.admin.cli import main, parser


def test_management_commands_cover_provisioning_and_panel_selection() -> None:
    args = parser().parse_args(
        [
            "user-create",
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
        ["user-inbounds", "alice", "--protocol", "trojan", "--tags", "TROJAN GRPC CDN TITAN"]
    )
    assert args.tags == ["TROJAN GRPC CDN TITAN"]
    for op in ["users", "inbounds", "sync"]:
        assert parser().parse_args([op]).operation == op


@pytest.mark.parametrize(
    "command",
    [
        ["link", "alice"],
        ["reconcile"],
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


def test_doctor_verifies_registry_and_vault(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.admin import worker
    from tests.conftest import ADMIN_KEY
    from tests.test_api import create

    create(client)
    app = client.app
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

    async def inventory(operation, args):
        return [{"username": "alice"}]

    monkeypatch.setattr(worker, "panel_operation", inventory)
    result = worker.execute("doctor", {})
    assert result["healthy"] is True
    assert result["canonical_registrations"] == result["retrievable_links"] == 1
    assert "token" not in str(result) and "subscription_url" not in str(result)
