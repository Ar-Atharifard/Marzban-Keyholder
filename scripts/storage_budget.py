"""Host-side budget coordination. Storage credentials never leave this process."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def repository_bytes(environment: dict[str, str]) -> int:
    """Count every stored version in the dedicated recovery bucket, including unfinished parts."""
    key = environment.get("AWS_ACCESS_KEY_ID", environment.get("B2_ACCOUNT_ID", ""))
    secret = environment.get("AWS_SECRET_ACCESS_KEY", environment.get("B2_ACCOUNT_KEY", ""))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    authorization = base64.b64encode((key + ":" + secret).encode()).decode()
    request = urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
        headers={"Authorization": "Basic " + authorization},
    )
    with opener.open(request, timeout=15) as response:
        account = json.load(response)
    allowed = account.get("allowed", {})
    if not allowed.get("bucketId") or allowed.get("namePrefix"):
        raise ValueError(
            "Capacity accounting requires dedicated bucket credentials without a prefix restriction"
        )
    endpoint = account["apiUrl"]
    if not re.fullmatch(r"https://api[0-9]+\.backblazeb2\.com", endpoint):
        raise ValueError("Unexpected storage endpoint")
    repository = environment["RESTIC_REPOSITORY"]
    bucket = (
        repository.split(":", 2)[1]
        if repository.startswith("b2:")
        else urllib.parse.urlsplit(repository.removeprefix("s3:")).path.strip("/").split("/")[0]
    )
    if allowed.get("bucketName") != bucket:
        raise ValueError("Recovery repository and measured bucket differ")

    def call(method: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint + "/b2api/v2/" + method,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": account["authorizationToken"],
                "Content-Type": "application/json",
            },
        )
        with opener.open(request, timeout=15) as response:
            result: dict[str, Any] = json.load(response)
        return result

    body = {"bucketId": allowed["bucketId"], "maxFileCount": 1000}
    total = 0
    for _ in range(100):
        page = call("b2_list_file_versions", body)
        total += sum(f.get("contentLength", 0) for f in page.get("files", []))
        if not page.get("nextFileName"):
            break
        body.update(startFileName=page["nextFileName"], startFileId=page["nextFileId"])
    else:
        raise ValueError("Recovery inventory exceeds workload limit")
    unfinished = call(
        "b2_list_unfinished_large_files", {"bucketId": allowed["bucketId"], "maxFileCount": 100}
    )
    if unfinished.get("nextFileId"):
        raise ValueError("Too many unfinished uploads; inspect before backing up")
    for item in unfinished.get("files", []):
        parts = call("b2_list_parts", {"fileId": item["fileId"], "maxPartCount": 1000})
        if parts.get("nextPartNumber"):
            raise ValueError("Too many unfinished parts")
        total += sum(p["contentLength"] for p in parts.get("parts", []))
    return int(total)


class Budget:
    def __init__(self, config: dict[str, Any], work: Path):
        if config.keys() - {"api_url", "api_env_file", "status_file", "keep_daily", "keep_weekly"}:
            raise ValueError("Unknown storage budget option")
        self.config = config
        self.work = work
        if work.is_symlink() or not work.is_dir() or work.stat().st_mode & 0o077:
            raise ValueError("Storage work directory must be private")
        self.url = config.get("api_url", "http://127.0.0.1:18000").rstrip("/")
        parsed = urllib.parse.urlsplit(self.url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ValueError("Budget API must be a trusted loopback endpoint")
        path = Path(config["api_env_file"])
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o077
            or (os.geteuid() == 0 and path.stat().st_uid != 0)
        ):
            raise ValueError("Budget API environment must be private")
        values = dict(
            line.split("=", 1)
            for line in path.read_text().splitlines()
            if line and not line.startswith("#") and "=" in line
        )
        self.key = values["KEYHOLDER_ADMIN_KEY"].strip().strip("\"'")
        self.reservation = "recovery:" + str(uuid4())
        self.capture_locked = False
        self.reserved = False

    def api(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        raw: bytes | None = None,
        maximum: int = 2 * 1024 * 1024,
        media_type: str = "application/json",
    ) -> Any:
        request = urllib.request.Request(
            self.url + "/admin" + path,
            method=method,
            data=raw
            if raw is not None
            else json.dumps(body).encode()
            if body is not None
            else None,
            headers={
                "Authorization": "Bearer " + self.key,
                "Idempotency-Key": str(uuid4()),
                "Content-Type": media_type,
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(request, timeout=35) as response:
                    value = response.read(maximum + 1)
                break
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt == 2:
                    raise
                delay = int(error.headers.get("Retry-After", "60"))
                if not 1 <= delay <= 60:
                    raise ValueError("Invalid API retry interval") from None
                time.sleep(delay)
        if len(value) > maximum:
            raise ValueError("Budget response exceeds limit")
        return value if path.endswith("/content") else json.loads(value)

    def measure(self) -> dict[str, Any]:
        self.api(
            "PUT", "/storage/usage/recovery", {"size_bytes": repository_bytes(dict(os.environ))}
        )
        if not self.capture_locked:
            self.api("POST", "/storage/reconcile")
        return dict(self.api("GET", "/storage"))

    def start(self) -> None:
        state = self.measure()
        if not state["enabled"]:
            raise ValueError("Storage admission is not enabled")
        self.api(
            "POST",
            "/storage/capture/start",
            {"reason": "Capture consistent receipt metadata and objects"},
        )
        self.capture_locked = True

    def capture_receipts(self, bundle: Path) -> None:
        records = []
        for offset in range(0, 100_000, 100):
            page = self.api("GET", f"/storage/receipt-manifest?limit=100&offset={offset}")
            records.extend(page)
            if len(page) < 100:
                break
        else:
            raise ValueError("Receipt inventory exceeds workload limit")
        for row in records:
            if (
                not re.fullmatch(r"[a-f0-9-]{36}", row["id"])
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                or not 0 < row["size_bytes"] <= 5 * 1024 * 1024
            ):
                raise ValueError("Invalid receipt identity")
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        total = sum(r["size_bytes"] for r in records)
        quota = self.api("GET", "/storage")["scopes"]["receipts"]["budget_bytes"]
        if total > quota:
            raise ValueError("Receipt recovery inventory exceeds its storage budget")
        cache = self.work / "receipt-cache"
        cache.mkdir(mode=0o700, exist_ok=True)
        if cache.is_symlink() or cache.stat().st_mode & 0o077 or cache.stat().st_uid != os.getuid():
            raise ValueError("Receipt cache must be private and owned by the recovery process")
        active = {row["sha256"] for row in records}
        for entry in cache.iterdir():
            if (
                entry.is_symlink()
                or not entry.is_file()
                or not re.fullmatch(r"[a-f0-9]{64}", entry.name)
            ):
                raise ValueError("Unknown receipt cache entry requires review")
            if entry.name not in active:
                entry.unlink()
        missing = sum(row["size_bytes"] for row in records if not (cache / row["sha256"]).exists())
        if shutil.disk_usage(bundle).free < missing + 64 * 1024 * 1024:
            raise ValueError("Insufficient staging space for receipt recovery")
        folder = bundle / "receipt-objects"
        folder.mkdir(mode=0o700)
        for row in records:
            identifier = row["id"]
            cached = cache / row["sha256"]
            if not cached.exists():
                data = self.api("GET", f"/receipts/{identifier}/content", maximum=5 * 1024 * 1024)
                if (
                    len(data) != row["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != row["sha256"]
                ):
                    raise ValueError("Receipt recovery checksum mismatch")
                descriptor, temporary = tempfile.mkstemp(dir=cache, prefix=".receipt-")
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, cached)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            if (
                cached.is_symlink()
                or cached.stat().st_mode & 0o077
                or cached.stat().st_uid != os.getuid()
                or cached.stat().st_size != row["size_bytes"]
            ):
                raise ValueError("Receipt cache metadata differs from its manifest")
            digest = hashlib.sha256()
            with cached.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("Receipt cache checksum mismatch")
            filename = "receipt-objects/" + identifier
            path = bundle / filename
            os.link(cached, path)
            manifest["files"].append(
                {
                    "path": filename,
                    "sha256": row["sha256"],
                    "size": row["size_bytes"],
                    "mode": 0o600,
                    "uid": os.getuid(),
                    "gid": os.getgid(),
                    "sqlite": False,
                }
            )
        manifest["receipt_objects"] = records
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def admit(self, bundle: Path) -> None:
        # A deliberately conservative bound: no reliance on compression or deduplication.
        files = [p for p in bundle.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        upper = (size * 110 + 99) // 100 + len(files) * 8192 + 16 * 1024 * 1024
        self.api(
            "POST",
            "/storage/reservations/" + self.reservation,
            {"scope": "recovery", "size_bytes": upper, "temporary": True},
        )
        self.reserved = True

    def restore_receipts(self, bundle: Path, manifest: dict[str, Any]) -> int:
        self.measure()
        count = 0
        for row in manifest.get("receipt_objects", []):
            identifier = row["id"]
            if (
                not re.fullmatch(r"[a-f0-9-]{36}", identifier)
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                or not 0 < row["size_bytes"] <= 5 * 1024 * 1024
            ):
                raise ValueError("Invalid receipt recovery identity")
            data = (bundle / "receipt-objects" / identifier).read_bytes()
            if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Receipt recovery integrity failure")
            self.api(
                "POST", f"/receipts/{identifier}/restore", raw=data, media_type=row["media_type"]
            )
            count += 1
        return count

    def release_capture(self) -> None:
        if self.capture_locked:
            self.api(
                "POST",
                "/storage/reservations/receipt-io/release",
                {"reason": "Receipt capture finished"},
            )
            self.capture_locked = False

    def finish(self, success: bool) -> None:
        self.release_capture()
        # Keep reservations if measurement fails: an interrupted upload may have stored data.
        self.measure()
        if self.reserved:
            self.api(
                "POST",
                "/storage/reservations/" + self.reservation + "/release",
                {
                    "reason": "Upload measured after completion"
                    if success
                    else "Failed upload measured; no snapshot retention applied"
                },
            )
            self.reserved = False
        state = self.api("GET", "/storage")
        if success and state.get("cleanup_enabled"):
            self.api(
                "POST",
                "/storage/receipts/cleanup",
                {"execute": True, "pressure": (state["scopes"]["receipts"]["percent"] or 0) >= 90},
            )
        self.save_status(blocked=not success)

    def save_status(self, *, blocked: bool = False, cleanup: str = "not-run") -> None:
        value = self.api("GET", "/storage")
        value.update(
            checked_at=dt.datetime.now(dt.UTC).isoformat(),
            operation_blocked=blocked,
            cleanup=cleanup,
        )  # noqa: UP017
        path = Path(self.config.get("status_file", str(self.work / "storage.json")))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".storage-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def maintain(self, run: Any, service_id: str) -> None:
        state = self.measure()
        scope = state["scopes"]["recovery"]
        headroom = state["total_bytes"] - state["accounted_bytes"]
        if headroom < 256 * 1024 * 1024:
            raise ValueError("Insufficient headroom for safe repository maintenance")
        if state.get("cleanup_enabled") and state["scopes"]["receipts"]["percent"] is not None:
            try:
                self.api(
                    "POST",
                    "/storage/receipts/cleanup",
                    {"execute": True, "pressure": state["scopes"]["receipts"]["percent"] >= 90},
                )
            except urllib.error.HTTPError as error:
                if error.code != 503:
                    raise
        if scope["used_bytes"] < scope["budget_bytes"] * 0.9:
            self.save_status(cleanup="below-recovery-high-water")
            return
        if not state.get("recovery_cleanup_enabled"):
            self.save_status(blocked=True, cleanup="recovery-cleanup-not-enabled")
            return
        snapshots = json.loads(
            run(
                [
                    "restic",
                    "snapshots",
                    "--host",
                    service_id,
                    "--tag",
                    "keyholder-recovery-v1,keyholder-complete",
                    "--json",
                ],
                timeout=60,
            )
        )
        ordered = sorted(snapshots, key=lambda s: (s["time"], s["id"]), reverse=True)
        protected = {s["id"] for s in ordered[:2]}
        for snapshot in reversed(ordered):
            if snapshot["id"] in protected:
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", snapshot["id"]):
                raise ValueError("Invalid snapshot identity")
            run(["restic", "forget", snapshot["id"]], timeout=300)
            run(["restic", "prune", "--max-repack-size=256M", "--max-unused=0"], timeout=1800)
            run(["restic", "check"], timeout=1800)
            current = self.measure()
            if current["scopes"]["recovery"]["used_bytes"] <= scope["budget_bytes"] * 0.8:
                self.save_status(cleanup="capacity-reclaimed")
                return
            if current["scopes"]["recovery"]["used_bytes"] >= scope["used_bytes"]:
                self.save_status(blocked=True, cleanup="awaiting-version-reclamation")
                return
            scope["used_bytes"] = current["scopes"]["recovery"]["used_bytes"]
        self.save_status(blocked=True, cleanup="protected-recovery-floor")
        raise ValueError("Recovery capacity cannot be reduced below protected snapshots")

    def preview(self, run: Any, service_id: str) -> dict[str, Any]:
        state = self.measure()
        snapshots = json.loads(
            run(
                [
                    "restic",
                    "snapshots",
                    "--host",
                    service_id,
                    "--tag",
                    "keyholder-recovery-v1,keyholder-complete",
                    "--json",
                ],
                timeout=60,
            )
        )
        ordered = sorted(snapshots, key=lambda s: (s["time"], s["id"]), reverse=True)
        return {
            "storage": state,
            "protected_snapshots": [{"id": s["id"], "time": s["time"]} for s in ordered[:2]],
            "oldest_first_candidates": [
                {"id": s["id"], "time": s["time"]} for s in reversed(ordered[2:])
            ],
            "prune_preview": run(
                ["restic", "prune", "--dry-run", "--max-repack-size=256M", "--max-unused=0"],
                timeout=300,
            ).decode()[:65536],
        }
