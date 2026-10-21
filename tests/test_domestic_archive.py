import io
import tarfile
from pathlib import Path

import pytest

from scripts.gate_backup import safe_member
from scripts.gate_snapshot import validate_archive
from scripts.restore_domestic import stage


@pytest.mark.parametrize("name", ["/etc/shadow", "etc/../shadow"])
def test_reject_traversal(tmp_path: Path, name: str) -> None:
    path = tmp_path / "gate.tar"
    with tarfile.open(path, "w") as archive:
        archive.addfile(tarfile.TarInfo(name))
    with pytest.raises(ValueError):
        validate_archive(path)


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_reject_links_and_special_files(tmp_path: Path, kind: bytes) -> None:
    path = tmp_path / "gate.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("etc/keyholder-rathole/config")
        member.type = kind
        member.linkname = "/etc/shadow"
        archive.addfile(member)
    with pytest.raises(ValueError):
        validate_archive(path)


def test_accept_regular_private_archive(tmp_path: Path) -> None:
    path = tmp_path / "gate.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("etc/keyholder-rathole/server.toml")
        member.size = 4
        archive.addfile(member, io.BytesIO(b"test"))
    validate_archive(path)


@pytest.mark.parametrize(
    "name", ["opt/marzban-node/.venv/bin/python", "a/__pycache__/b", "a/.git/b"]
)
def test_capture_excludes_environment_and_caches(name: str) -> None:
    assert safe_member(tarfile.TarInfo(name)) is None


def test_incomplete_restore_never_publishes_staging_directory(tmp_path: Path) -> None:
    archive_path = tmp_path / "gate.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(tarfile.TarInfo("etc/keyholder-domestic/armed"))
    target = tmp_path / "staged"
    with pytest.raises(ValueError, match="incomplete"):
        stage(archive_path, target)
    assert not target.exists()


def test_unexpected_member_is_rejected_even_without_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "gate.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(tarfile.TarInfo("etc/shadow"))
    with pytest.raises(ValueError, match="Unexpected"):
        stage(archive_path, tmp_path / "staged")


def test_restore_refuses_existing_destination(tmp_path: Path) -> None:
    archive_path = tmp_path / "gate.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(tarfile.TarInfo("etc/keyholder-domestic/armed"))
    target = tmp_path / "staged"
    target.mkdir()
    (target / "existing").write_text("keep")
    with pytest.raises(ValueError, match="already exists"):
        stage(archive_path, target)
    assert (target / "existing").read_text() == "keep"
