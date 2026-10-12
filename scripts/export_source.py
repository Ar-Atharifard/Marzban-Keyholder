"""Export reviewed source without Git history, private notes or runtime credentials."""

import argparse
import gzip
import json
import re
import subprocess
import tarfile
from pathlib import Path

EXCLUDED = {".git", ".private", ".audit", ".venv", "dist", "build", "data", "logs"}


def source_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    )
    files: list[Path] = []
    for name in sorted(set(output.decode().split("\0")) - {""}):
        path = Path(name)
        if set(path.parts) & EXCLUDED or path.name == ".keyholder-admin.json":
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            raise ValueError("Runtime environment tracked; publication refused")
        if path.suffix in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}:
            raise ValueError("Sensitive runtime file tracked; publication refused")
        actual = root / path
        if not actual.exists():
            continue
        if actual.is_symlink():
            raise ValueError("Symlink export refused")
        if actual.is_file():
            files.append(path)
    return files


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--private-patterns", type=Path)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = source_files(root)
    patterns = json.loads(args.private_patterns.read_text()) if args.private_patterns else []
    for name in files:
        data = (root / name).read_bytes()
        if re.search(rb"(?m)^-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----\r?$", data) or any(
            str(x).encode() in data for x in patterns
        ):
            raise ValueError("Private material detected; publication refused")
    with args.output.open("xb") as target:
        try:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name in files:
                        info = archive.gettarinfo(
                            str(root / name), arcname="keyholder/" + str(name)
                        )
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mtime = 0
                        with (root / name).open("rb") as file:
                            archive.addfile(info, file)
        except Exception:
            args.output.unlink(missing_ok=True)
            raise
    print(f"Exported {len(files)} source files without private data or Git history.")


if __name__ == "__main__":
    main()
