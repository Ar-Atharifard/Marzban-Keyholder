import hashlib
import json
from pathlib import Path

import pytest

from scripts.release_manifest import write_manifest

COMMIT = "a" * 40
IMAGE = "ghcr.io/example/keyholder@sha256:" + "b" * 64


def test_release_identity_and_artifact_integrity(tmp_path: Path) -> None:
    artifact = tmp_path / "keyholder.whl"
    artifact.write_bytes(b"synthetic wheel")
    (tmp_path / ".gitignore").write_text("*")
    write_manifest(tmp_path, COMMIT, IMAGE, "0.2.0")
    manifest = json.loads((tmp_path / "release.json").read_text())
    assert ".gitignore" not in manifest["artifacts"]
    assert manifest["commit"] == COMMIT
    assert manifest["api_image"] == IMAGE
    assert manifest["artifacts"][artifact.name] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    for line in (tmp_path / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError, match="already exists"):
        write_manifest(tmp_path, COMMIT, IMAGE, "0.2.0")


@pytest.mark.parametrize(
    ("commit", "image", "version"),
    [
        ("master", IMAGE, "0.2.0"),
        (COMMIT, "ghcr.io/example/keyholder:latest", "0.2.0"),
        (COMMIT, IMAGE, "../../bad"),
    ],
)
def test_rejects_ambiguous_release_identity(
    tmp_path: Path, commit: str, image: str, version: str
) -> None:
    (tmp_path / "artifact").write_text("synthetic")
    with pytest.raises(ValueError):
        write_manifest(tmp_path, commit, image, version)
    assert not (tmp_path / "release.json").exists()
