"""Run inside the API container; communicate only with its loopback API."""

import asyncio
import json
import logging
import os
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_KINDS = ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]
KINDS = [*DEFAULT_KINDS, "ws_tls_cdn", "xhttp_tls_cdn"]


class OperatorError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = Request(
        "http://127.0.0.1:18000" + path,
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
            f"API returned HTTP {error.code}; inspect the customer state."
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
        matches = [c for c in customers() if c["mapping"]["upstream_username"] == selector]
        if len(matches) != 1:
            raise OperatorError("Username is missing or ambiguous; use its customer ID.") from None
        return matches[0]
    return api("GET", "/admin/customers/" + identifier)  # type: ignore[no-any-return]


async def upstream(username: str, profiles: list[str]) -> dict[str, Any]:
    import httpx

    from keyholder.backends.base import UpstreamError, UpstreamUnavailable
    from keyholder.backends.marzban import MarzbanBackend
    from keyholder.config import Settings
    from keyholder.rendering.profiles import generate_profiles
    from keyholder.schemas import Policy

    settings = Settings()  # type: ignore[call-arg]
    try:
        async with asyncio.timeout(settings.upstream_timeout):
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                links = await MarzbanBackend(settings, client).configurations(username)
                result = generate_profiles(links, Policy(profiles=profiles))  # type: ignore[arg-type]
    except (UpstreamError, UpstreamUnavailable, TimeoutError, ValueError):
        raise OperatorError("Marzban user is unavailable or has no compatible profiles.") from None
    kinds = sorted({p.kind for p in result})
    return {"available_profiles": kinds, "missing_profiles": sorted(set(profiles) - set(kinds))}


def execute(operation: str, args: dict[str, Any]) -> Any:
    if operation == "health":
        return api("GET", "/health")
    if operation == "list":
        return api("GET", f"/admin/customers?limit={args['limit']}&offset={args['offset']}")
    if operation == "create":
        username = args["username"]
        matches = [c for c in customers() if c["mapping"]["upstream_username"] == username]
        if matches:
            raise OperatorError("This Marzban username is already attached; show its customer.")
        profiles = args.get("profiles") or DEFAULT_KINDS
        check = asyncio.run(upstream(username, profiles))
        if check["missing_profiles"]:
            raise OperatorError("Selected profiles are missing in Marzban; check user inbounds.")
        return api(
            "POST",
            "/admin/customers",
            {
                "name": args["name"],
                "upstream_username": username,
                "policy": {"profiles": profiles},
            },
        )
    customer = resolve(args["customer"])
    path = "/admin/customers/" + quote(customer["id"], safe="")
    if operation == "show":
        return customer
    if operation == "check":
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
            raise OperatorError("Replacement Marzban user lacks selected profiles.")
        return api(
            "PUT",
            path + "/mapping",
            {"backend_id": "marzban-default", "upstream_username": args["username"]},
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
        if args["profiles"]:
            check = asyncio.run(
                upstream(customer["mapping"]["upstream_username"], args["profiles"])
            )
            if check["missing_profiles"]:
                raise OperatorError("Selected profiles are missing in Marzban.")
        return api("PATCH", path, {"policy": {"profiles": args["profiles"]}})
    raise OperatorError("Unsupported operation.")


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
