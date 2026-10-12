import json
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from keyholder import cli
from scripts.export_source import source_files


def test_config_initializer_creates_keys_without_printing_or_overwriting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / ".env"
    assert cli.main(["init-config", "--output", str(path)]) == 0
    content = path.read_text()
    values = dict(line.split("=", 1) for line in content.splitlines())
    assert len(values["KEYHOLDER_ADMIN_KEY"]) >= 32
    Fernet(values["KEYHOLDER_TOKEN_ENCRYPTION_KEY"].encode())
    assert values["KEYHOLDER_ADMIN_KEY"] not in capsys.readouterr().out
    assert path.stat().st_mode & 0o777 == 0o600
    assert cli.main(["init-config", "--output", str(path)]) == 1
    assert path.read_text() == content


def test_source_export_excludes_private_notes_but_includes_untracked_source(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".private/\n.env\n")
    (tmp_path / "README.md").write_text("Public")
    p = tmp_path / ".private"
    p.mkdir()
    (p / "personal.md").write_text("Private")
    (tmp_path / ".env").write_text("private")
    assert source_files(tmp_path) == [Path(".gitignore"), Path("README.md")]


def test_export_refuses_tracked_credentials(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".env").write_text("private")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".env"], check=True)
    with pytest.raises(ValueError, match="publication refused"):
        source_files(tmp_path)


def test_client_configuration_is_generic_and_backend_selection_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "admin.json"
    config.write_text(
        json.dumps({"host": "another-server", "remote_path": "/opt/operator/host.py"})
    )
    monkeypatch.setenv("KEYHOLDER_ADMIN_CONFIG", str(config))
    args = cli.parser().parse_args(["--backend", "west", "list"])
    assert args.host == "another-server" and args.backend_id == "west"
    assert cli.remote_path() == "/opt/operator/host.py"


def test_operator_username_lookup_is_scoped_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.admin import worker

    rows = [
        {
            "id": "east-customer",
            "mapping": {"backend_id": "east", "upstream_username": "alice"},
            "status": "active",
        },
        {
            "id": "west-customer",
            "mapping": {"backend_id": "west", "upstream_username": "alice"},
            "status": "active",
        },
    ]
    monkeypatch.setattr(worker, "customers", lambda: rows)
    assert (
        worker.execute("show", {"customer": "alice", "backend_id": "east"})["id"] == "east-customer"
    )
    assert (
        worker.execute("show", {"customer": "alice", "backend_id": "west"})["id"] == "west-customer"
    )
    assert worker.backend_id() == "marzban-default"
