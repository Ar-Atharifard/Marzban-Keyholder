"""Administrator grammar for the private ledger and receipt lifecycle."""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

GROUP_HELP = {
    "purchase": "Record purchases and outstanding amounts.",
    "payment": "Record and verify incoming bank payments.",
    "referral": "Attribute recommendations and list gift eligibility.",
    "gift": "Record delivered referral gifts and corrections.",
    "receipt": "Upload, retrieve and protect private receipt images.",
    "storage": "Inspect storage budgets and preview safe image cleanup.",
    "billing": "Inspect balances and financial action history.",
}


def add_parsers(group: Any, leaf: Any) -> None:
    specs = {
        "purchase": ["create", "list", "show", "cancel"],
        "payment": [
            "create",
            "list",
            "show",
            "confirm",
            "void",
            "refund",
            "allocate",
            "allocations",
            "refunds",
            "unallocate",
        ],
        "referral": ["create", "list"],
        "gift": ["create", "list", "reverse"],
        "receipt": ["upload", "list", "download", "keep", "release"],
        "storage": ["status", "reconcile", "reservations", "cleanup", "release-reservation"],
        "billing": ["balances", "actions"],
    }
    for resource, actions in specs.items():
        _, commands = group(resource)
        for action in actions:
            operation = f"billing-{resource}-{action}"
            p = leaf(
                resource,
                commands,
                action,
                operation,
                f"{action.capitalize()} {resource} records; use --help for required fields.",
            )
            p.add_argument("--key", help="Retry identity; generated and printed if omitted")
            customer = (resource in {"purchase", "payment", "referral"} and action == "create") or (
                resource == "billing" and action == "balances"
            )
            if customer:
                p.add_argument("customer", help="Existing customer selector")
            if action == "list" and resource in {"purchase", "payment", "referral", "gift"}:
                p.add_argument(
                    "--customer", help="Customer selector; for referrals/gifts, the recommender"
                )
            if action in {
                "show",
                "cancel",
                "confirm",
                "void",
                "refund",
                "allocate",
                "allocations",
                "refunds",
                "unallocate",
                "reverse",
                "upload",
                "download",
                "keep",
                "release",
                "release-reservation",
            } or (resource == "receipt" and action == "list"):
                p.add_argument("id", help="Record UUID (allocation UUID for unallocate)")
            if resource in {"purchase", "payment"} and action == "create":
                p.add_argument("--amount", required=True, help="Exact decimal amount")
                p.add_argument(
                    "--currency",
                    choices=["IRR", "USDT", "LTC"] if resource == "purchase" else ["IRR"],
                    default="IRR",
                )
                p.add_argument("--unit", choices=["currency", "toman"], default="currency")
            if resource == "purchase" and action == "create":
                p.add_argument("--description", required=True)
                p.add_argument("--quota-bytes", type=int)
                p.add_argument("--duration-days", type=int)
                p.add_argument("--purchased-at", help="ISO timestamp with timezone")
            if resource == "payment" and action == "create":
                p.add_argument("--receiving-account", required=True, help="Nonsecret account alias")
                p.add_argument("--reference")
                p.add_argument("--notes", default="")
                p.add_argument("--received-at", help="ISO timestamp with timezone")
            if resource == "payment" and action in {"refund", "allocate"}:
                p.add_argument("--amount", required=True)
            if resource == "payment" and action == "allocate":
                p.add_argument("--purchase-id", required=True)
            if resource == "referral" and action == "create":
                p.add_argument("--referrer", required=True, help="Existing recommender selector")
                p.add_argument("--introduced-at", help="ISO timestamp with timezone")
            if resource == "referral" and action == "list":
                p.add_argument("--state", choices=["all", "eligible", "considered"], default="all")
                p.add_argument("--since", help="Inclusive introduction timestamp with timezone")
                p.add_argument("--until", help="Exclusive introduction timestamp with timezone")
            if resource == "gift" and action == "create":
                p.add_argument("--referrer", required=True)
                p.add_argument("--description", required=True)
                p.add_argument("--referral-ids", nargs="+", required=True)
                p.add_argument("--delivered-at", help="ISO timestamp with timezone")
            if action in {
                "cancel",
                "confirm",
                "void",
                "refund",
                "unallocate",
                "reverse",
                "keep",
                "release",
                "release-reservation",
            }:
                p.add_argument("--reason", required=True)
            if action in {
                "cancel",
                "confirm",
                "void",
                "refund",
                "allocate",
                "unallocate",
                "reverse",
                "keep",
                "release",
                "release-reservation",
            } or (resource == "gift" and action == "create"):
                p.add_argument(
                    "--confirm",
                    action="store_true",
                    dest="confirmed",
                    help="Apply the displayed explicit action",
                )
            if resource == "receipt" and action == "upload":
                p.add_argument("file", type=Path)
            if resource == "receipt" and action == "download":
                p.add_argument("--output", type=Path, required=True, help="New private image file")
            if resource == "storage" and action == "cleanup":
                p.add_argument(
                    "--execute",
                    action="store_true",
                    help="Delete eligible images; otherwise preview",
                )
                p.add_argument(
                    "--pressure",
                    action="store_true",
                    help="Include oldest eligible images to reach 80% usage",
                )
                p.add_argument("--confirm", action="store_true", dest="confirmed")
            if action in {"list", "actions", "reservations", "allocations", "refunds"}:
                p.add_argument("--limit", type=int, default=50)
                p.add_argument("--offset", type=int, default=0)


def payload(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        k: v
        for k, v in vars(args).items()
        if k not in {"operation", "resource", "action", "host", "json", "local", "file", "output"}
        and v is not None
    }
    if (
        hasattr(args, "confirmed")
        and not args.confirmed
        and (args.action != "cleanup" or args.execute)
    ):
        raise ValueError("Review the record and supply --confirm to apply this action")
    values["key"] = values.get("key") or str(uuid4())
    if args.resource == "receipt" and args.action == "upload":
        with args.file.open("rb") as stream:
            raw = stream.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError("Receipt exceeds 5 MiB")
        values["content"] = base64.b64encode(raw).decode()
        values["media_type"] = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    return {"operation": args.operation, "args": values}


def run(args: argparse.Namespace, request: Any) -> int:
    try:
        envelope = payload(args)
        print("Request key: " + envelope["args"]["key"], file=sys.stderr)
        if args.resource == "receipt" and args.action == "download" and args.output.exists():
            raise ValueError("Output already exists")
        result = (
            request(args.host, envelope, local=True)["result"]
            if args.local
            else request(args.host, envelope)["result"]
        )
        if args.resource == "receipt" and args.action == "download":
            raw = base64.b64decode(result["content"], validate=True)
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            print("Receipt saved privately.")
        else:
            from keyholder.operator_output import render

            print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
