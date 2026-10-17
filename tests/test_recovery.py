import datetime as dt
import getpass
import io
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import monitor, recovery


def fixture_config(tmp_path: Path) -> dict[str, Any]:
    secret = tmp_path / "application.env"
    secret.write_text("TEST_KEY=synthetic-not-a-real-key\n")
    secret.chmod(0o600)
    database = tmp_path / "application.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE customers (id TEXT, token TEXT)")
        db.execute("INSERT INTO customers VALUES ('stable-id', 'synthetic-token')")
    return {
        "service_id": "test",
        "files": {"rootfs/etc/app/env": str(secret)},
        "sqlite": {"volumes/app/data.sqlite3": str(database)},
    }


def test_capture_stage_preserves_database_identity_and_private_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    recovery.capture(fixture_config(tmp_path), bundle)
    manifest = recovery.verify(bundle)
    assert len(manifest["files"]) == 2
    stage = tmp_path / "restored"
    recovery.stage(bundle, stage)
    with sqlite3.connect(stage / "volumes/app/data.sqlite3") as db:
        assert db.execute("SELECT * FROM customers").fetchall() == [
            ("stable-id", "synthetic-token")
        ]
    assert (stage / "rootfs/etc/app/env").stat().st_mode & 0o777 == 0o600
    assert bundle.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("change", ["tamper", "extra", "missing", "symlink", "traversal"])
def test_verify_refuses_corrupt_or_unsafe_bundles(tmp_path: Path, change: str) -> None:
    bundle = tmp_path / "bundle"
    recovery.capture(fixture_config(tmp_path), bundle)
    target = bundle / "rootfs/etc/app/env"
    if change == "tamper":
        target.write_text("changed")
    elif change == "extra":
        (bundle / "extra").write_text("unexpected")
    elif change == "missing":
        target.unlink()
    elif change == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "application.env")
    else:
        manifest_path = bundle / "manifest.json"
        value = json.loads(manifest_path.read_text())
        value["files"][0]["path"] = "../outside"
        manifest_path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        recovery.verify(bundle)


def test_capture_and_stage_refuse_existing_targets(tmp_path: Path) -> None:
    config = fixture_config(tmp_path)
    bundle = tmp_path / "bundle"
    recovery.capture(config, bundle)
    with pytest.raises(FileExistsError):
        recovery.capture(config, bundle)
    target = tmp_path / "live"
    target.mkdir()
    marker = target / "preserve"
    marker.write_text("existing")
    with pytest.raises(FileExistsError):
        recovery.stage(bundle, target)
    assert marker.read_text() == "existing"


@pytest.mark.parametrize("kind", ["sqlite-as-file", "link", "overlap", "missing"])
def test_capture_failure_cleans_only_new_bundle(tmp_path: Path, kind: str) -> None:
    config = fixture_config(tmp_path)
    if kind == "sqlite-as-file":
        config["files"]["rootfs/database"] = str(tmp_path / "application.sqlite3")
    elif kind == "link":
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "application.env")
        config["files"]["rootfs/link"] = str(link)
    elif kind == "overlap":
        config["sqlite"]["rootfs/etc/app/env"] = str(tmp_path / "application.sqlite3")
    else:
        config["files"]["rootfs/missing"] = str(tmp_path / "missing")
    with pytest.raises((ValueError, OSError)):
        recovery.capture(config, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    assert (tmp_path / "application.env").exists()


def test_tree_preserves_file_and_directory_modes(tmp_path: Path) -> None:
    tree = tmp_path / "website"
    tree.mkdir(mode=0o755)
    (tree / "index.html").write_text("synthetic site")
    config = {"service_id": "test", "trees": {"rootfs/opt/site": str(tree)}}
    recovery.capture(config, tmp_path / "bundle")
    recovery.stage(tmp_path / "bundle", tmp_path / "stage")
    assert (tmp_path / "stage/rootfs/opt/site").stat().st_mode & 0o777 == 0o755


def test_upload_failure_never_marks_success_and_removes_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture_config(tmp_path)
    password = tmp_path / "password"
    password.write_text("synthetic-recovery-password")
    password.chmod(0o600)
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:repo")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    calls: list[list[str]] = []

    def failed(args: list[str], timeout: int = 60) -> bytes:
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(recovery, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        recovery.upload(config, work, tmp_path / "status.json")
    assert not (work / "bundle").exists()
    assert not (tmp_path / "status.json").exists()
    assert len(calls) == 1  # No retention/deletion after a failed upload.


def test_upload_success_records_capture_age_and_scopes_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture_config(tmp_path)
    password = tmp_path / "password"
    password.write_text("synthetic-recovery-password")
    password.chmod(0o600)
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:repo")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    calls: list[list[str]] = []

    def successful(args: list[str], timeout: int = 60) -> bytes:
        calls.append(args)
        return b"{}"

    monkeypatch.setattr(recovery, "run", successful)
    status = tmp_path / "status.json"
    recovery.upload(config, work, status)
    value = json.loads(status.read_text())
    assert value["capture_started_at"] <= value["uploaded_at"]
    assert status.stat().st_mode & 0o777 == 0o600
    assert "--keep-daily" in calls[1] and "--prune" not in calls[1]
    assert "--host" in calls[1] and "--tag" in calls[1]
    assert not (work / "bundle").exists()


def test_plaintext_stale_bundle_is_not_implicitly_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESTIC_REPOSITORY", "b2:synthetic:repo")
    password = tmp_path / "password"
    password.write_text("synthetic")
    password.chmod(0o600)
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    (work / "bundle").mkdir()
    with pytest.raises(ValueError, match="Previous bundle"):
        recovery.upload({}, work, tmp_path / "status")
    assert (work / "bundle").exists()


@pytest.mark.parametrize("state", ["fresh", "old", "missing", "invalid", "future"])
def test_offsite_alert_uses_successful_capture_age(tmp_path: Path, state: str) -> None:
    now = dt.datetime.now(dt.UTC)
    path = tmp_path / "status.json"
    config = {"offsite_backup_status_file": str(path)}
    offset = 25 if state == "old" else -2 if state == "future" else 2
    if state != "missing":
        path.write_text(
            "not json"
            if state == "invalid"
            else json.dumps(
                {
                    "capture_started_at": (now - dt.timedelta(hours=offset)).isoformat(),
                    "uploaded_at": now.isoformat(),
                }
            )
        )
    assert bool(monitor.offsite_backup_alerts(config, now.timestamp())) == (state != "fresh")
    assert not monitor.offsite_backup_alerts({}, now.timestamp())


def test_private_configuration_permissions(tmp_path: Path) -> None:
    path = tmp_path / "config"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        recovery.private_json(path)
    path.chmod(0o600)
    assert recovery.private_json(path) == {}


def test_b2_setup_hides_secrets_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "synthetic-bucket")
    answers = iter(["syntheticKeyId", "syntheticApplicationKey123456", "x" * 40, "x" * 40])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    directory = tmp_path / "private"
    recovery.configure_b2(directory)
    contents = (directory / "recovery.env").read_text()
    assert "b2:synthetic-bucket:keyholder" in contents
    assert (directory / "recovery.env").stat().st_mode & 0o777 == 0o600
    assert (directory / "recovery-password").read_text() == "x" * 40
    assert capsys.readouterr().out == ""
    with pytest.raises(ValueError):
        recovery.configure_b2(directory)


def test_b2_setup_rejects_environment_injection_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "synthetic-bucket")
    answers = iter(["syntheticKeyId", "invalid\nKEY=injection", "x" * 40, "x" * 40])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    directory = tmp_path / "private"
    with pytest.raises(ValueError):
        recovery.configure_b2(directory)
    assert not (directory / "recovery.env").exists()
    assert not (directory / "recovery-password").exists()


def test_active_deployment_discovery_does_not_export_container_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose = tmp_path / "release.json"
    compose.write_text('{"services":{}}')
    image_id = "sha256:" + "a" * 64

    def docker(args: list[str], timeout: int = 60) -> bytes:
        if args[1] == "inspect":
            return json.dumps(
                [
                    {
                        "Image": image_id,
                        "Config": {
                            "Env": ["SECRET=do-not-export-inspect"],
                            "Labels": {
                                "com.docker.compose.project.config_files": str(compose),
                                "com.docker.compose.project": "app",
                                "com.docker.compose.service": "api",
                            },
                        },
                    }
                ]
            ).encode()
        assert args[1] == "save"
        Path(args[args.index("--output") + 1]).write_bytes(b"synthetic-image-archive")
        return b""

    monkeypatch.setattr(recovery, "run", docker)
    config = recovery.discover({"service_id": "test", "containers": ["app"]})
    recovery.capture(config, tmp_path / "bundle")
    manifest = recovery.verify(tmp_path / "bundle")
    assert manifest["images"][0]["id"] == image_id
    assert "SECRET" not in json.dumps(manifest)
    assert "rootfs/" + str(compose).lstrip("/") in config["files"]
    newer = tmp_path / "new-release.json"
    newer.write_text('{"services":{}}')
    compose.unlink()
    compose = newer
    refreshed = recovery.discover(config)
    assert str(newer) in refreshed["compose_files"]
    assert not any(path.endswith("/release.json") for path in refreshed["files"])


@pytest.mark.parametrize("valid", [True, False])
def test_s3_preparation_validates_endpoint_and_preserves_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    import urllib.request

    path = tmp_path / "recovery.env"
    original = (
        "RESTIC_REPOSITORY=b2:synthetic-bucket:keyholder\n"
        "RESTIC_PASSWORD_FILE=/private/password\n"
        "B2_ACCOUNT_ID=syntheticId\nB2_ACCOUNT_KEY=syntheticSecret\n"
    )
    path.write_text(original)
    path.chmod(0o600)
    response = {
        "s3ApiUrl": "https://s3.eu-central-003.backblazeb2.com"
        if valid
        else "https://evil.invalid",
        "allowed": {"bucketId": "synthetic", "bucketName": "synthetic-bucket"},
    }
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode())
        ),
    )
    if valid:
        recovery.prepare_s3(path)
        env = recovery.repository_environment(path)
        assert env["RESTIC_PASSWORD_FILE"] == "/private/password"
        assert env["AWS_SECRET_ACCESS_KEY"] == "syntheticSecret"
        assert env["RESTIC_REPOSITORY"].startswith("s3:https://s3.eu-central-003.")
        assert path.stat().st_mode & 0o777 == 0o600
        assert "B2_ACCOUNT_KEY" not in env
    else:
        with pytest.raises(ValueError):
            recovery.prepare_s3(path)
        assert path.read_text() == original
