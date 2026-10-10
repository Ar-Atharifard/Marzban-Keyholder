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
