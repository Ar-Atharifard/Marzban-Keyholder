"""Private, portable recovery bundles and encrypted off-host backup (Python 3.10+).

Never writes into the live filesystem during verification or staging. Runtime
configuration and image archives stay on the machine performing the backup.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import getpass
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

try:
    from scripts.backup_database import backup_database
except ModuleNotFoundError:
    from backup_database import backup_database  # type: ignore[no-redef,import-not-found]

SCHEMA = 1


def repository_environment(path: Path) -> dict[str, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Repository environment must be private")
    if os.geteuid() == 0 and info.st_uid != 0:
        raise ValueError("Repository environment must be root-owned")
    allowed = {
        "RESTIC_REPOSITORY",
        "RESTIC_PASSWORD_FILE",
        "RESTIC_CACHE_DIR",
        "GOGC",
        "B2_ACCOUNT_ID",
        "B2_ACCOUNT_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    }
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key not in allowed or key in result or not value or "\x00" in value:
            raise ValueError("Invalid repository environment")
        result[key] = value
    return result


def prepare_s3(path: Path) -> None:
    """Resolve B2's official S3 endpoint without exposing credentials off-host."""
    import base64

    env = repository_environment(path)
    if not env["RESTIC_REPOSITORY"].startswith("b2:"):
        raise ValueError("Expected uninitialized B2 bootstrap configuration")
    _, bucket, prefix = env["RESTIC_REPOSITORY"].split(":", 2)
    credentials = base64.b64encode(
        (env["B2_ACCOUNT_ID"] + ":" + env["B2_ACCOUNT_KEY"]).encode()
    ).decode()
    request = urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
        headers={"Authorization": "Basic " + credentials},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=20) as response:
        authorization = json.load(response)
    endpoint = authorization["s3ApiUrl"]
    if not re.fullmatch(r"https://s3\.[a-z0-9-]+\.backblazeb2\.com", endpoint):
        raise ValueError("Unexpected B2 S3 endpoint")
    scope = authorization.get("allowed", {})
    if not scope.get("bucketId") or scope.get("bucketName") != bucket:
        raise ValueError("Use a key restricted to the configured bucket")
    env["RESTIC_REPOSITORY"] = f"s3:{endpoint}/{bucket}/{prefix}"
    env["AWS_ACCESS_KEY_ID"] = env.pop("B2_ACCOUNT_ID")
    env["AWS_SECRET_ACCESS_KEY"] = env.pop("B2_ACCOUNT_KEY")
    env["AWS_DEFAULT_REGION"] = endpoint.split(".")[1]
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".recovery-env-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            for key, value in env.items():
                stream.write(f"{key}={value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure_b2(directory: Path, values: dict[str, str] | None = None) -> None:
    """Prompt privately; credentials never enter shell history or chat."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Configuration directory must be private")
    env = directory / "recovery.env"
    password_file = directory / "recovery-password"
    if env.exists() or env.is_symlink() or password_file.exists() or password_file.is_symlink():
        raise ValueError("Existing credentials must not be overwritten")
    if values is None:
        values = {
            "bucket": input("Private B2 bucket name: "),
            "key_id": getpass.getpass("Application key ID (hidden): "),
            "key": getpass.getpass("Application key (hidden): "),
            "password": getpass.getpass("Repository password (save in password manager first): "),
            "confirmation": getpass.getpass("Repeat repository password: "),
        }
    if (
        not isinstance(values, dict)
        or set(values) != {"bucket", "key_id", "key", "password", "confirmation"}
        or not all(isinstance(value, str) for value in values.values())
    ):
        raise ValueError("Complete B2 credential fields required")
    bucket, key_id, key = (values[name].strip() for name in ["bucket", "key_id", "key"])
    password, confirmation = values["password"], values["confirmation"]
    if not re.fullmatch(r"[A-Za-z0-9-]{6,63}", bucket):
        raise ValueError("Invalid bucket name")
    if not re.fullmatch(r"[A-Za-z0-9]{1,128}", key_id):
        raise ValueError("Invalid application key ID")
    if not re.fullmatch(r"[A-Za-z0-9+/_=-]{16,200}", key):
        raise ValueError("Invalid application key")
    if len(password) < 32 or "\n" in password or "\r" in password or password != confirmation:
        raise ValueError("Password must match and contain at least 32 characters")
    descriptor = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(password)
        descriptor = os.open(env, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(f"RESTIC_REPOSITORY=b2:{bucket}:keyholder\n")
            stream.write(f"RESTIC_PASSWORD_FILE={password_file}\n")
            stream.write(f"B2_ACCOUNT_ID={key_id}\nB2_ACCOUNT_KEY={key}\n")
            stream.write("RESTIC_CACHE_DIR=/var/cache/keyholder-recovery\nGOGC=50\n")
    except BaseException:
        password_file.unlink(missing_ok=True)
        raise


def private_json(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Configuration must be a private regular file")
    if os.geteuid() == 0 and info.st_uid != 0:
        raise ValueError("Configuration must belong to root")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected object")
    return value


def relative(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or any(p in {".", ".."} for p in value.split("/")):
        raise ValueError("Unsafe bundle path")
    return path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def run(args: list[str], timeout: int = 60) -> bytes:
    # Capture output: subprocess exceptions and tool output can contain credentials.
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout


def regular_tree(path: Path) -> list[Path]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Expected real directory")
    result = []
    for parent, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            child = Path(parent) / name
            mode = child.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("Symlinks and special files require explicit handling")
            if stat.S_ISREG(mode):
                result.append(child)
    return sorted(result)


def discover(config: dict[str, Any]) -> dict[str, Any]:
    """Include the actual active Compose files, never an assumed checkout release."""
    result: dict[str, Any] = json.loads(json.dumps(config))
    files = result.setdefault("files", {})
    for old in result.pop("compose_files", []):
        key = "rootfs/" + old.lstrip("/")
        if files.get(key) == old:
            files.pop(key)
    active: set[str] = set()
    for container in result.get("containers", []):
        item = json.loads(run(["docker", "inspect", container]))[0]
        labels = item["Config"].get("Labels") or {}
        paths = labels.get("com.docker.compose.project.config_files", "")
        if not paths:
            raise ValueError("Container has no deployment file inventory")
        for name in paths.split(","):
            path = Path(name)
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ValueError("Active Compose configuration is unavailable")
            files["rootfs/" + str(path).lstrip("/")] = str(path)
            active.add(str(path))
    result["compose_files"] = sorted(active)
    return result


def capture(config: dict[str, Any], output: Path) -> None:
    if config.keys() - {"files", "trees", "sqlite", "containers", "service_id", "compose_files"}:
        raise ValueError("Unknown capture field")
    if config.get("containers"):
        config = discover(config)
    service_id = config["service_id"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", service_id):
        raise ValueError("Invalid stable service identity")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    records: list[dict[str, Any]] = []
    directories: dict[str, dict[str, Any]] = {}
    claimed: set[str] = set()

    def add(source: Path, name: str, sqlite: bool = False) -> None:
        target = output / relative(name)
        if name in claimed:
            raise ValueError("Overlapping capture entries")
        claimed.add(name)
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Capture sources must be regular files")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ancestor, original = Path(name).parent, source.parent
        while ancestor != Path("."):
            parent_info = original.stat()
            directories[str(ancestor)] = {
                "path": str(ancestor),
                "mode": stat.S_IMODE(parent_info.st_mode) & 0o777,
                "uid": parent_info.st_uid,
                "gid": parent_info.st_gid,
            }
            ancestor, original = ancestor.parent, original.parent
        if sqlite:
            backup_database(source, target)
        else:
            # Do not mistake a live SQLite database or WAL for an ordinary file.
            with source.open("rb") as reader:
                header = reader.read(16)
            if header == b"SQLite format 3\x00" or source.name.endswith(("-wal", "-shm")):
                raise ValueError("SQLite sources must be declared separately")
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            target.chmod(0o600)
            after = source.stat()
            if (info.st_ino, info.st_size, info.st_mtime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Source changed while capturing")
        records.append(
            {
                "path": name,
                "sha256": digest(target),
                "size": target.stat().st_size,
                "mode": stat.S_IMODE(info.st_mode),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "sqlite": sqlite,
            }
        )

    try:
        for kind in ("files", "sqlite"):
            for name, source in config.get(kind, {}).items():
                add(Path(source), name, sqlite=kind == "sqlite")
        for name, source in config.get("trees", {}).items():
            root = Path(source)
            relative(name)
            for item in regular_tree(root):
                add(item, str(Path(name) / item.relative_to(root)))
        images = []
        projects: dict[str, list[str]] = {}
        for container in config.get("containers", []):
            inspected = json.loads(run(["docker", "inspect", container]))[0]
            image = inspected["Image"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                raise ValueError("Expected immutable Docker image identity")
            image_path = "images/" + image.removeprefix("sha256:") + ".tar"
            if image_path not in claimed:
                destination = output / image_path
                destination.parent.mkdir(mode=0o700, exist_ok=True)
                run(["docker", "save", "--output", str(destination), image], timeout=900)
                destination.chmod(0o600)
                records.append(
                    {
                        "path": image_path,
                        "sha256": digest(destination),
                        "size": destination.stat().st_size,
                        "mode": 0o600,
                        "uid": 0,
                        "gid": 0,
                        "sqlite": False,
                    }
                )
                claimed.add(image_path)
            labels = inspected["Config"].get("Labels") or {}
            # Only nonsecret identity metadata is recorded here; never dump inspect's Env.
            project = labels.get("com.docker.compose.project")
            compose_files = labels.get("com.docker.compose.project.config_files", "").split(",")
            if not project or not all(compose_files):
                raise ValueError("Missing Compose project metadata")
            if any("rootfs/" + name.lstrip("/") not in claimed for name in compose_files):
                raise ValueError("Deployment changed while capturing")
            if project in projects and projects[project] != compose_files:
                raise ValueError("Inconsistent Compose project metadata")
            projects[project] = compose_files
            images.append(
                {
                    "container": container,
                    "id": image,
                    "archive": image_path,
                    "project": labels.get("com.docker.compose.project"),
                    "service": labels.get("com.docker.compose.service"),
                }
            )
        manifest = {
            "schema": SCHEMA,
            "service_id": service_id,
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),  # noqa: UP017
            "files": records,
            "directories": list(directories.values()),
            "images": images,
            "compose_projects": [
                {"name": name, "files": paths} for name, paths in projects.items()
            ],
        }
        with (output / "manifest.json").open("x") as stream:
            json.dump(manifest, stream, indent=2)
        (output / "manifest.json").chmod(0o600)
        verify(output)
    except BaseException:
        shutil.rmtree(output)
        raise


def verify(bundle: Path) -> dict[str, Any]:
    manifest = private_json(bundle / "manifest.json")
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported recovery schema")
    actual = {str(p.relative_to(bundle)) for p in regular_tree(bundle)}
    declared: set[str] = {"manifest.json"}
    for record in manifest.get("directories", []):
        relative(record["path"])
        if not isinstance(record["mode"], int) or record["mode"] & ~0o777:
            raise ValueError("Unsafe directory permissions")
    for record in manifest["files"]:
        name = record["path"]
        source = bundle / relative(name)
        if name in declared:
            raise ValueError("Duplicate manifest entry")
        declared.add(name)
        if source.stat().st_size != record["size"] or digest(source) != record["sha256"]:
            raise ValueError("Recovery integrity failure")
        if not isinstance(record["mode"], int) or record["mode"] & ~0o777:
            raise ValueError("Unsafe restored permissions")
    if actual != declared:
        raise ValueError("Recovery file inventory mismatch")
    return manifest


def stage(bundle: Path, destination: Path) -> None:
    manifest = verify(bundle)
    # Stage into a new directory, never directly onto the live filesystem.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for record in manifest["files"]:
            name = relative(record["path"])
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(bundle / name, target)
            target.chmod(record["mode"] & 0o777)
            if os.geteuid() == 0:
                os.chown(target, record["uid"], record["gid"])
        for record in sorted(
            manifest.get("directories", []), key=lambda r: len(Path(r["path"]).parts), reverse=True
        ):
            name = relative(record["path"])
            mode = record["mode"]
            if not isinstance(mode, int) or mode & ~0o777:
                raise ValueError("Unsafe directory permissions")
            target = destination / name
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.chmod(mode)
            if os.geteuid() == 0:
                os.chown(target, record["uid"], record["gid"])
    except BaseException:
        shutil.rmtree(destination)
        raise


def upload(config: dict[str, Any], work: Path, status: Path) -> None:
    # systemd's EnvironmentFile supplies RESTIC_REPOSITORY/PASSWORD_FILE/B2 keys.
    # Deliberately no automatic repository init or prune during a daily upload.
    if not os.getenv("RESTIC_REPOSITORY") or not os.getenv("RESTIC_PASSWORD_FILE"):
        raise ValueError("Restic repository and separate password file required")
    private_json_path = Path(os.environ["RESTIC_PASSWORD_FILE"])
    info = private_json_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Repository password must be private")
    if work.is_symlink() or not work.is_dir() or work.stat().st_mode & 0o077:
        raise ValueError("Work directory must be private")
    # Fixed backup path enables incremental restic matching; flock excludes overlap.
    with (work / "backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bundle = work / "bundle"
        if bundle.exists():
            # A failed run may retain secrets. Refuse implicit deletion of unknown data.
            raise ValueError("Previous bundle requires operator review")
        started = dt.datetime.now(dt.timezone.utc).isoformat()  # noqa: UP017
        try:
            capture(config, bundle)
            run(
                [
                    "restic",
                    "backup",
                    "--host",
                    config["service_id"],
                    "--tag",
                    "keyholder-recovery-v1",
                    "--json",
                    str(bundle),
                ],
                timeout=1800,
            )
            # Retention is logical deletion only; repository compaction is separate.
            run(
                [
                    "restic",
                    "forget",
                    "--host",
                    config["service_id"],
                    "--tag",
                    "keyholder-recovery-v1",
                    "--group-by",
                    "host,tags",
                    "--keep-daily",
                    "7",
                    "--keep-weekly",
                    "4",
                ],
                timeout=300,
            )
            status.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=status.parent, prefix=".backup-")
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(
                        {
                            "capture_started_at": started,
                            "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),  # noqa: UP017
                        },
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, status)
            finally:
                Path(temporary).unlink(missing_ok=True)
        finally:
            if bundle.exists():
                shutil.rmtree(bundle)


def maintain(work: Path) -> None:
    """Hold the shared lock across repository checks and compaction."""
    if work.is_symlink() or not work.is_dir() or work.stat().st_mode & 0o077:
        raise ValueError("Work directory must be private")
    with (work / "backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        full = dt.datetime.now(dt.timezone.utc).day <= 7  # noqa: UP017
        run(["restic", "check", "--read-data" if full else "--read-data-subset=5%"], timeout=1800)
        run(["restic", "prune", "--max-repack-size=256M", "--max-unused=10%"], timeout=1800)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    configure = commands.add_parser("configure-b2", help="Privately prompt for B2 credentials")
    configure.add_argument("--directory", type=Path, default=Path("/etc/keyholder"))
    configure.add_argument(
        "--stdin-json", action="store_true", help="Accept hidden automation input on stdin"
    )
    s3 = commands.add_parser("prepare-s3", help="Resolve and configure Backblaze's recommended API")
    s3.add_argument("--environment", type=Path, default=Path("/etc/keyholder/recovery.env"))
    inventory = commands.add_parser(
        "inventory", help="Include active Compose files in capture config"
    )
    inventory.add_argument("--seed", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    create = commands.add_parser("capture", help="Create new private recovery bundle")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="Verify inventory and checksums")
    check.add_argument("--bundle", type=Path, required=True)
    restore = commands.add_parser("stage", help="Verify and stage into a NEW directory only")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    remote = commands.add_parser("upload", help="Capture and upload to initialized restic repo")
    remote.add_argument("--config", type=Path, required=True)
    remote.add_argument("--work", type=Path, required=True)
    remote.add_argument("--status", type=Path, required=True)
    maintenance = commands.add_parser("maintain", help="Check and compact the existing repository")
    maintenance.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "configure-b2":
            values = None
            if args.stdin_json:
                raw = sys.stdin.read(8193)
                if len(raw) > 8192:
                    raise ValueError("Credential input exceeds limit")
                values = json.loads(raw)
                if not isinstance(values, dict):
                    raise ValueError("Credential input must be an object")
            configure_b2(args.directory, values)
        elif args.action == "prepare-s3":
            prepare_s3(args.environment)
        elif args.action == "maintain":
            maintain(args.work)
        elif args.action == "inventory":
            config = discover(private_json(args.seed))
            with args.output.open("x") as stream:
                json.dump(config, stream, indent=2)
            args.output.chmod(0o600)
        elif args.action == "capture":
            capture(private_json(args.config), args.output)
        elif args.action == "verify":
            verify(args.bundle)
        elif args.action == "stage":
            stage(args.bundle, args.destination)
        else:
            upload(private_json(args.config), args.work, args.status)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "Recovery failed; inspect private configuration and tool status.\n")
    print("Recovery operation completed; treat all recovery files as secrets.")


if __name__ == "__main__":
    main()
