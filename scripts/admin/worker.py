"""Run inside the API container; communicate only with its loopback API."""

import asyncio
import json
import logging
import os
import sys
from contextvars import ContextVar
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from keyholder.profile_types import DEFAULT_PROFILES, SUPPORTED_KINDS

DEFAULT_KINDS: list[str] = list(DEFAULT_PROFILES)
KINDS = list(SUPPORTED_KINDS)
SELECTED: ContextVar[str] = ContextVar("backend_id", default="marzban-default")


def backend_id() -> str:
    return SELECTED.get()


class OperatorError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = Request(
        os.getenv("KEYHOLDER_OPERATOR_API_URL", "http://127.0.0.1:18000").rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["KEYHOLDER_ADMIN_KEY"],
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise OperatorError("API response exceeds the operator limit.")
            return json.loads(data)
    except HTTPError as error:
        raise OperatorError(
            f"API returned HTTP {error.code}; inspect the customer state.", status=error.code
        ) from None


def customers() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(0, 2000, 100):
        page = api("GET", f"/admin/customers?limit=100&offset={offset}")
        rows.extend(page)
        if len(page) < 100:
            return rows
    raise OperatorError("Lookup exceeded 2000 customers; use a customer ID.")


def resolve(selector: str) -> dict[str, Any]:
    from uuid import UUID

    try:
        identifier = str(UUID(selector))
    except ValueError:
        matches = [
            c
            for c in customers()
            if c["mapping"]["upstream_username"] == selector
            and c["mapping"]["backend_id"] == backend_id()
            and c["status"] != "revoked"
        ]
        if not matches:
            raise OperatorError(
                "No Keyholder registration for this username; run keyholder create USER first. "
                "Use the exact Marzban username."
            ) from None
        if len(matches) > 1:
            raise OperatorError(
                "Username has multiple registrations; use its customer ID."
            ) from None
        return matches[0]
    return api("GET", "/admin/customers/" + identifier)  # type: ignore[no-any-return]


async def upstream(username: str, profiles: list[str]) -> dict[str, Any]:
    import httpx

    from keyholder.backends.base import UpstreamError, UpstreamUnavailable
    from keyholder.backends.registry import build_backends
    from keyholder.config import Settings
    from keyholder.rendering.profiles import allowed_cdn, generate_profiles
    from keyholder.schemas import Policy

    settings = Settings()  # type: ignore[call-arg]
    try:
        async with asyncio.timeout(settings.upstream_timeout):
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                adapters = build_backends(settings, client)
                adapter = adapters.get(backend_id())
                if adapter is None:
                    raise ValueError("Backend not configured")
                links = await adapter.configurations(username)
                authoritative = settings.profile_source in {"marzban", "upstream"}
                result = generate_profiles(
                    links,
                    Policy.model_validate(
                        {"profiles": list(settings.enabled_profiles) if authoritative else profiles}
                    ),
                    settings.allowed_cdn_networks,
                )
                result = [
                    p
                    for p in result
                    if allowed_cdn(p, settings.allowed_cdn_hosts, settings.allowed_cdn_networks)
                ]
                if not result:
                    raise ValueError("No allowed profiles")
    except (UpstreamError, UpstreamUnavailable, TimeoutError, ValueError):
        raise OperatorError(
            "Upstream account is unavailable or has no compatible profiles."
        ) from None
    kinds = sorted({p.kind for p in result})
    return {
        "available_profiles": kinds,
        "missing_profiles": [] if authoritative else sorted(set(profiles) - set(kinds)),
    }


def execute(operation: str, args: dict[str, Any]) -> Any:
    token = SELECTED.set(
        args.get("backend_id", os.getenv("KEYHOLDER_OPERATOR_BACKEND_ID", "marzban-default"))
    )
    try:
        return _execute(operation, args)
    finally:
        SELECTED.reset(token)


def _execute(operation: str, args: dict[str, Any]) -> Any:
    if operation == "backends":
        return api("GET", "/admin/backends")
    if operation == "backend-register":
        return api("POST", "/admin/backends/register")
    if operation in {
        "users",
        "inbounds",
        "sync",
        "reconcile",
        "user-create",
        "user-update",
        "user-inbounds",
        "user-usage",
        "user-reset-usage",
    }:
        return asyncio.run(panel_operation(operation, args))
    if operation == "doctor":
        import sqlite3

        from sqlalchemy.engine import make_url

        from keyholder.config import Settings
        from keyholder.vault import decrypt

        settings = Settings()  # type: ignore[call-arg]
        filename = make_url(settings.database_url).database
        with sqlite3.connect("file:" + str(filename) + "?mode=ro", uri=True) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            foreign_keys = not db.execute("PRAGMA foreign_key_check").fetchall()
            revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            rows = db.execute(
                "SELECT c.token_encrypted,c.token_hash FROM registrations r "
                "JOIN customers c ON c.id=r.customer_id "
                "WHERE c.status!='revoked' AND r.backend_id=?",
                (backend_id(),),
            ).fetchall()
            archived = db.execute(
                "SELECT count(*) FROM customers c JOIN customer_mappings m ON m.customer_id=c.id "
                "WHERE c.status='revoked' AND m.backend_id=?",
                (backend_id(),),
            ).fetchone()[0]
            canonical = db.execute(
                "SELECT upstream_username FROM registrations WHERE backend_id=?", (backend_id(),)
            ).fetchall()
        retrievable = 0
        for encrypted, digest in rows:
            try:
                decrypt(settings, encrypted, digest)
                retrievable += 1
            except ValueError:
                pass
        from keyholder.backends.registry import backend_configs

        selected = next((c for c in backend_configs(settings) if c.id == backend_id()), None)
        if selected is None:
            raise OperatorError("Backend not configured.")
        users = (
            asyncio.run(panel_operation("users", {})) if selected.provider == "marzban" else None
        )
        names = {u["username"] for u in users} if users is not None else None
        mapped = {r[0] for r in canonical}
        return {
            "backend_id": backend_id(),
            "database_integrity": integrity,
            "foreign_keys": foreign_keys,
            "revision": revision,
            "marzban_users": len(users) if users is not None else None,
            "canonical_registrations": len(canonical),
            "revoked_history": archived,
            "retrievable_links": retrievable,
            "profile_source": settings.profile_source,
            "cdn_hosts": settings.allowed_cdn_hosts,
            "registration_inventory_matches": names == mapped if names is not None else None,
            "healthy": integrity
            and foreign_keys
            and (names is None or names == mapped)
            and retrievable == len(rows),
        }
    if operation == "health":
        return api("GET", "/health")
    if operation == "list":
        rows = [c for c in customers() if c["mapping"]["backend_id"] == backend_id()]
        if not args.get("history"):
            rows = [c for c in rows if c["status"] != "revoked"]
        return rows[args["offset"] : args["offset"] + args["limit"]]
    if operation == "create":
        username = args["username"]
        matches = [
            c
            for c in customers()
            if c["mapping"]["upstream_username"] == username
            and c["mapping"]["backend_id"] == backend_id()
        ]
        active = [c for c in matches if c["status"] != "revoked"]
        if len(active) == 1:
            return api("GET", "/admin/customers/" + active[0]["id"] + "/subscription")
        if len(active) > 1:
            raise OperatorError("Legacy duplicates require keyholder reconcile --confirm.")
        profiles = args.get("profiles") or (
            KINDS
            if os.getenv("KEYHOLDER_PROFILE_SOURCE") in {"marzban", "upstream"}
            else DEFAULT_KINDS
        )
        check = asyncio.run(upstream(username, profiles))
        if check["missing_profiles"]:
            raise OperatorError(
                "Selected profiles are missing upstream; check provider selections."
            )
        return api(
            "POST",
            "/admin/customers",
            {
                "name": args["name"],
                "upstream_username": username,
                "backend_id": backend_id(),
                "policy": {"profiles": profiles},
            },
        )
    customer = resolve(args["customer"])
    path = "/admin/customers/" + quote(customer["id"], safe="")
    if operation == "link":
        return api("GET", path + "/subscription")
    if operation == "show":
        return {**customer, "profile_source": os.getenv("KEYHOLDER_PROFILE_SOURCE", "policy")}
    if operation == "check":
        SELECTED.set(customer["mapping"]["backend_id"])
        return {
            "customer_id": customer["id"],
            "local_status": customer["status"],
            **asyncio.run(
                upstream(customer["mapping"]["upstream_username"], customer["policy"]["profiles"])
            ),
        }
    if operation == "remap":
        check = asyncio.run(upstream(args["username"], customer["policy"]["profiles"]))
        if check["missing_profiles"]:
            raise OperatorError("Replacement upstream account lacks selected profiles.")
        return api(
            "PUT",
            path + "/mapping",
            {"backend_id": backend_id(), "upstream_username": args["username"]},
        )
    if operation == "rotate-token":
        if not args.get("confirmed"):
            raise OperatorError("Rotation requires explicit confirmation; old links stop working.")
        return api("POST", path + "/rotate-token")
    if operation == "revoke":
        if not args.get("confirmed"):
            raise OperatorError("Revocation requires explicit confirmation and is permanent.")
        return api("PATCH", path, {"status": "revoked"})
    if operation in {"enable", "disable"}:
        return api("PATCH", path, {"status": "active" if operation == "enable" else "disabled"})
    if operation == "rename":
        return api("PATCH", path, {"name": args["name"]})
    if operation == "profiles":
        SELECTED.set(customer["mapping"]["backend_id"])
        if os.getenv("KEYHOLDER_PROFILE_SOURCE") in {"marzban", "upstream"}:
            raise OperatorError("The provider controls profiles; use its management interface.")
        if args["profiles"]:
            check = asyncio.run(
                upstream(customer["mapping"]["upstream_username"], args["profiles"])
            )
            if check["missing_profiles"]:
                raise OperatorError("Selected profiles are missing upstream.")
        return api("PATCH", path, {"policy": {"profiles": args["profiles"]}})
    raise OperatorError("Unsupported operation.")


def summary(user: dict[str, Any]) -> dict[str, Any]:
    return {
        k: user.get(k)
        for k in ["username", "status", "data_limit", "used_traffic", "expire", "inbounds"]
    }


async def panel_operation(operation: str, args: dict[str, Any]) -> Any:
    import time

    import httpx

    from keyholder.backends.marzban import MarzbanBackend
    from keyholder.backends.registry import build_backends
    from keyholder.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=settings.upstream_timeout
    ) as client:
        adapter = build_backends(settings, client).get(backend_id())
        if not isinstance(adapter, MarzbanBackend):
            raise OperatorError("Selected provider does not support panel management.")
        backend = adapter
        await backend.login()

        async def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
            kwargs: dict[str, Any] = {"headers": {"Authorization": "Bearer " + backend.token}}
            if body is not None:
                kwargs["json"] = body
            return (await backend.request(method, path, **kwargs)).json()

        if operation == "inbounds":
            data = await call("GET", "/api/inbounds")
            return {
                protocol: [
                    {k: item.get(k) for k in ["tag", "protocol", "network", "tls", "port"]}
                    for item in items
                ]
                for protocol, items in data.items()
            }
        if operation in {"users", "sync", "reconcile"}:
            data = await call("GET", "/api/users?limit=1000")
            if data["total"] > len(data["users"]):
                raise OperatorError("User inventory exceeds reconciliation limit.")
            users = data["users"]
            if operation == "users":
                return [summary(u) for u in users]
            if operation == "reconcile" and not args.get("confirmed"):
                raise OperatorError("Reconciliation rotates old links; --confirm required.")
            existing = customers()
            count = 0
            revoked = 0
            for user in users:
                name = user["username"]
                matches = sorted(
                    [
                        c
                        for c in existing
                        if c["mapping"]["upstream_username"] == name
                        and c["mapping"]["backend_id"] == backend_id()
                        and c["status"] != "revoked"
                    ],
                    key=lambda c: (c["created_at"], c["id"]),
                )
                if operation == "reconcile" and matches:
                    # Rotate only unrecoverable legacy registrations; retry does not rotate again.
                    try:
                        api("GET", "/admin/customers/" + matches[0]["id"] + "/subscription")
                    except OperatorError as error:
                        if error.status != 409:
                            raise
                        api("POST", "/admin/customers/" + matches[0]["id"] + "/rotate-token")
                    for duplicate in matches[1:]:
                        api("PATCH", "/admin/customers/" + duplicate["id"], {"status": "revoked"})
                        revoked += 1
                elif not matches:
                    api(
                        "POST",
                        "/admin/customers",
                        {"name": name, "upstream_username": name, "backend_id": backend_id()},
                    )
                    count += 1
            return {"marzban_users": len(users), "registered": count, "duplicates_revoked": revoked}
        name = args["username"]
        path = "/api/user/" + quote(name, safe="")
        if operation == "user-usage":
            return await call("GET", path + "/usage")
        if operation == "user-reset-usage":
            if not args.get("confirmed"):
                raise OperatorError("Traffic reset requires --confirm; used traffic becomes zero.")
            return summary(await call("POST", path + "/reset"))
        if operation == "user-create":
            body = {
                "username": name,
                "proxies": {p: {} for p in args["protocols"]},
                "inbounds": {},
                "data_limit": int(args["quota_gb"] * 1024**3),
                "expire": int(time.time()) + args["days"] * 86400 if args["days"] else 0,
            }
            await call("POST", "/api/user", body)
            return api(
                "POST",
                "/admin/customers",
                {"name": name, "upstream_username": name, "backend_id": backend_id()},
            )
        user = await call("GET", path)
        if operation == "user-update":
            body = {}
            if args.get("quota_gb") is not None:
                body["data_limit"] = int(args["quota_gb"] * 1024**3)
            if args.get("days") is not None:
                body["expire"] = int(time.time()) + args["days"] * 86400 if args["days"] else 0
            if args.get("status") is not None:
                body["status"] = args["status"]
        else:
            # Preserve every existing protocol credential while changing the requested selection.
            available = await call("GET", "/api/inbounds")
            allowed = {item["tag"] for item in available.get(args["protocol"], [])}
            if not set(args["tags"]) <= allowed:
                raise OperatorError("An inbound tag does not belong to the selected protocol.")
            proxies = user["proxies"]
            proxies.setdefault(args["protocol"], {})
            inbounds = user["inbounds"]
            inbounds[args["protocol"]] = args["tags"]
            body = {"proxies": proxies, "inbounds": inbounds}
        return summary(await call("PUT", path, body))


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        payload = json.loads(sys.stdin.buffer.read(16385))
        result = execute(payload["operation"], payload["args"])
        print(json.dumps({"ok": True, "result": result}))
    except OperatorError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "Operation failed; credentials and diagnostics withheld."}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
