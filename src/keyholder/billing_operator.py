"""Translate administrator CLI/bot commands into the private HTTP API."""

import base64
from typing import Any
from urllib.parse import urlencode


def execute(operation: str, args: dict[str, Any], api: Any, resolve: Any) -> Any:
    _, resource, action = operation.split("-", 2)
    values = {
        k: v
        for k, v in args.items()
        if k
        not in {
            "key",
            "backend_id",
            "confirmed",
            "id",
            "limit",
            "offset",
            "customer",
            "referrer",
            "content",
            "media_type",
            "state",
            "since",
            "until",
        }
        and v is not None
    }
    identifier = args.get("id", "")
    if len(identifier) > 128 or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:"
        for c in identifier
    ):
        raise ValueError("Invalid record identity")
    key = args["key"]
    if args.get("customer"):
        cid = resolve(args["customer"])["id"]
        if action == "create":
            values["customer_id"] = cid
    else:
        cid = None
    if args.get("referrer"):
        values["referrer_id"] = resolve(args["referrer"])["id"]
    query = {k: args[k] for k in ("limit", "offset") if k in args}
    if cid:
        query["referrer_id" if resource in {"gift", "referral"} else "customer_id"] = cid
    if resource == "referral" and args.get("state"):
        query["state"] = args["state"]
    for boundary in ("since", "until"):
        if resource == "referral" and args.get(boundary):
            query[boundary] = args[boundary]
    suffix = "?" + urlencode(query) if query else ""
    plural = {
        "purchase": "purchases",
        "payment": "payments",
        "referral": "referrals",
        "gift": "gifts",
    }
    if resource in plural and action == "create":
        return api("POST", "/admin/" + plural[resource], values, key=key)
    if resource in plural and action == "list":
        return api("GET", "/admin/" + plural[resource] + suffix)
    if resource in {"purchase", "payment"} and action == "show":
        return api("GET", f"/admin/{plural[resource]}/{identifier}")
    if resource == "purchase" and action == "cancel":
        return api("POST", f"/admin/purchases/{identifier}/cancel", values, key=key)
    if resource == "payment":
        if action == "unallocate":
            return api("POST", f"/admin/allocations/{identifier}/reverse", values, key=key)
        target = {"refund": "refunds", "allocate": "allocations"}.get(action, action)
        return api(
            "GET" if action in {"allocations", "refunds"} else "POST",
            f"/admin/payments/{identifier}/{target}"
            + (suffix if action in {"allocations", "refunds"} else ""),
            None if action in {"allocations", "refunds"} else values,
            key=key,
        )
    if resource == "gift" and action == "reverse":
        return api("POST", f"/admin/gifts/{identifier}/reverse", values, key=key)
    if resource == "billing":
        return api(
            "GET",
            f"/admin/customers/{cid}/balances"
            if action == "balances"
            else "/admin/billing/actions" + suffix,
        )
    if resource == "receipt":
        if action == "upload":
            raw = base64.b64decode(args["content"], validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError("Receipt exceeds size limit")
            return api(
                "POST",
                f"/admin/payments/{identifier}/receipts",
                key=key,
                data=raw,
                media_type=args["media_type"],
            )
        if action == "download":
            raw = api(
                "GET", f"/admin/receipts/{identifier}/content", raw=True, maximum=5 * 1024 * 1024
            )
            return {"content": base64.b64encode(raw).decode()}
        if action == "list":
            return api("GET", f"/admin/payments/{identifier}/receipts" + suffix)
        return api(
            "POST",
            f"/admin/receipts/{identifier}/protection",
            {**values, "keep": action == "keep"},
            key=key,
        )
    if resource == "storage":
        if action == "status":
            return api("GET", "/admin/storage")
        if action == "reservations":
            return api("GET", "/admin/storage/reservations" + suffix)
        if action == "reconcile":
            return api("POST", "/admin/storage/reconcile")
        if action == "cleanup":
            return api("POST", "/admin/storage/receipts/cleanup", values)
        if action == "release-reservation":
            return api("POST", f"/admin/storage/reservations/{identifier}/release", values, key=key)
    raise ValueError("Unsupported ledger operation")
