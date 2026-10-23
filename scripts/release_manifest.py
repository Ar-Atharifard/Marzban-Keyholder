"""Record a release's source commit, immutable image and downloadable artifacts."""

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path


def write_manifest(directory: Path, commit: str, image: str, version: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full Git commit is required")
    if not re.fullmatch(r"ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("Use an immutable GHCR image digest")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Use a numeric major.minor.patch project version")
    files = sorted(p for p in directory.iterdir() if p.name != ".gitignore")
    if not files or any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError("Expected regular release artifacts")
    if any(p.name in {"release.json", "SHA256SUMS"} for p in files):
        raise ValueError("Release output already exists")
    hashes = {}
    for path in files:
        with path.open("rb") as stream:
            hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "schema": 1,
        "version": version,
        "commit": commit,
        "api_image": image,
        "platform": "linux/amd64",
        "artifacts": hashes,
    }
    output = directory / "release.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    hashes[output.name] = hashlib.sha256(output.read_bytes()).hexdigest()
    (directory / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    write_manifest(args.directory, args.commit, args.image, version)


if __name__ == "__main__":
    main()
