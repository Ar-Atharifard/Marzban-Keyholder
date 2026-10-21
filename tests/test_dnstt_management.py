import json
import os
from pathlib import Path
from typing import Any

import pytest

from keyholder import cli
from scripts.admin import host


def test_dnstt_is_not_a_customer_command() -> None:
    with pytest.raises(SystemExit):
        cli.main(["user", "dnstt", "alice"])
    assert ("personal", "dnstt") in cli.parser().command_parsers
    assert ("user", "dnstt") not in cli.parser().command_parsers


def test_owner_export_has_no_dependency_on_marzban(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = tmp_path / "personal.json"
    profile = {"profile_uri": "vless://personal-secret", "transport": {"domain": "t.example"}}
    file.write_text(json.dumps(profile))
    file.chmod(0o600)
    monkeypatch.setattr(
        host, "configuration", lambda: {"api_container": "unused", "dnstt_client_file": str(file)}
    )
    monkeypatch.setattr(os, "getuid", lambda: 0)
    original = Path.stat

    def owned(path: Path, *args: Any, **kwargs: Any) -> Any:
        stat = original(path, *args, **kwargs)
        return os.stat_result(
            (
                stat.st_mode,
                stat.st_ino,
                stat.st_dev,
                stat.st_nlink,
                0,
                stat.st_gid,
                stat.st_size,
                stat.st_atime,
                stat.st_mtime,
                stat.st_ctime,
            )
        )

    monkeypatch.setattr(Path, "stat", owned)
    assert host.execute({"operation": "personal-dnstt"})["result"] == profile
    file.chmod(0o644)
    with pytest.raises(ValueError):
        host.execute({"operation": "personal-dnstt"})


def test_dnstt_cli_requires_private_file_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["personal", "dnstt"])
    output = tmp_path / "owner.json"
    payload = {"profile_uri": "PRIVATE-OWNER-CREDENTIAL", "transport": {"domain": "t.example"}}
    monkeypatch.setattr(cli, "request", lambda *a, **kw: {"ok": True, "result": payload})
    assert cli.main(["personal", "dnstt", "--save-link", str(output)]) == 0
    assert json.loads(output.read_text()) == payload
    assert output.stat().st_mode & 0o777 == 0o600
    assert "PRIVATE-OWNER-CREDENTIAL" not in capsys.readouterr().out
    assert cli.main(["personal", "dnstt", "--save-link", str(output)]) == 1
