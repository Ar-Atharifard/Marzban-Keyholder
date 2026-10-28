"""Private ledger commands for the existing allowlisted management bot."""

from __future__ import annotations

import base64
import contextlib
import io
import secrets
import time
import urllib.request
from collections.abc import Callable
from typing import Any
from uuid import uuid4


def command(
    name: str,
    words: list[str],
    state: dict[str, Any],
    dispatch: Any,
    confirmation_seconds: int,
    render: Callable[[Any], str],
) -> str:
    from keyholder import billing_cli
    from keyholder.cli import parser

    if name == "billinghelp":
        return (
            "Ledger commands use ACTION and key=value options. All money is exact text.\n"
            '/purchase create USER amount=100 unit=toman description="30 days"\n'
            "/purchase list customer=USER\n"
            "/payment create USER amount=1000 receiving_account=personal reference=BANKREF\n"
            '/payment confirm PAYMENT_ID reason="Verified in bank history"\n'
            "/payment allocate PAYMENT_ID purchase_id=PURCHASE_ID amount=1000\n"
            '/payment refund PAYMENT_ID amount=100 reason="Returned funds"\n'
            '/payment unallocate ALLOCATION_ID reason="Correction"\n'
            "/referral create USER referrer=RECOMMENDER\n"
            "/referral list customer=RECOMMENDER state=eligible\n"
            '/gift create referrer=USER description="Delivered gift" referral_ids=ID1,ID2\n'
            '/gift reverse GIFT_ID reason="Entry correction"\n'
            "/billing balances USER\n"
            "/receipt upload PAYMENT_ID — then send a photo or PNG/JPEG document\n"
            "/receipt list PAYMENT_ID\n"
            '/receipt keep RECEIPT_ID reason="Dispute"\n'
            '/receipt release RECEIPT_ID reason="Resolved"\n'
            "/storage status\n"
            "/storage reconcile\n"
            "/storage cleanup — preview; execute=true pressure=true to apply\n"
            "Use the CLI help for all options. /confirm CODE applies a reviewed change.\n"
            "Images are retained in Telegram too; B2 expiry does not delete chat copies."
        )
    if name == "receipt" and words and words[0] == "upload":
        if len(words) != 2:
            raise ValueError("Usage: /receipt upload PAYMENT_ID")
        dispatch("billing-payment-show", {"id": words[1], "key": str(uuid4())})
        state["receipt_upload"] = {
            "payment_id": words[1],
            "key": str(uuid4()),
            "expires": time.time() + confirmation_seconds,
        }
        return (
            "Send the receipt photo or JPEG/PNG document within five minutes. "
            "Payment verification stays separate."
        )
    if name == "receipt" and words and words[0] == "download":
        raise ValueError(
            "Use the SSH CLI receipt download --output to retrieve the original privately."
        )
    if not words:
        raise ValueError("Specify an action; use /billinghelp")
    argv = [name, words[0]]
    execute = False
    for word in words[1:]:
        if "=" not in word:
            argv.append(word)
            continue
        key, value = word.split("=", 1)
        if key == "execute":
            if value not in {"true", "false"}:
                raise ValueError("execute must be true or false")
            execute = value == "true"
            if execute:
                argv.append("--execute")
        elif key == "pressure":
            if value not in {"true", "false"}:
                raise ValueError("pressure must be true or false")
            if value == "true":
                argv.append("--pressure")
        else:
            argv.extend(
                ["--" + key.replace("_", "-"), *value.split(",")]
                if key == "referral_ids"
                else ["--" + key.replace("_", "-"), value]
            )
    destructive = (
        words[0]
        in {
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
        }
        or (name == "gift" and words[0] == "create")
        or execute
    )
    if destructive:
        argv.append("--confirm")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser().parse_args(argv)
    except SystemExit:
        raise ValueError("Invalid ledger command; use /billinghelp or CLI help") from None
    payload = billing_cli.payload(args)
    if destructive:
        code = secrets.token_hex(3)
        state["pending"] = {
            "code": code,
            "operation": payload["operation"],
            "args": payload["args"],
            "expires": time.time() + confirmation_seconds,
        }
        return (
            "Review change:\n"
            + render(payload["args"])
            + f"\nConfirm within five minutes with /confirm {code}"
        )
    result = dispatch(payload["operation"], payload["args"])
    return "Request key: " + str(payload["args"]["key"]) + "\n" + render(result)


def receive(
    token: str,
    message: dict[str, Any],
    state: dict[str, Any],
    telegram: Any,
    dispatch: Any,
    base: str,
    render: Callable[[Any], str],
) -> str:
    pending = state.get("receipt_upload", {})
    if pending.get("expires", 0) < time.time():
        raise ValueError("Use /receipt upload PAYMENT_ID before sending an image")
    photo = message.get("photo", [])
    file = photo[-1] if photo else message.get("document", {})
    if not file.get("file_id") or file.get("file_size", 0) > 5 * 1024 * 1024:
        raise ValueError("Use a JPEG/PNG image up to 5 MiB")
    metadata = telegram(token, "getFile", {"file_id": file["file_id"]})["result"]
    path = metadata["file_path"]
    if (
        not isinstance(path, str)
        or any(part in {"", ".."} for part in path.split("/"))
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-"
            for c in path
        )
    ):
        raise ValueError("Invalid Telegram file path")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        base.rstrip("/") + "/file/bot" + token + "/" + path, timeout=20
    ) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("Receipt exceeds size limit")
    result = dispatch(
        "billing-receipt-upload",
        {
            "id": pending["payment_id"],
            "key": pending["key"],
            "content": base64.b64encode(raw).decode(),
            "media_type": "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg",
        },
    )
    state.pop("receipt_upload", None)
    return render(result)
