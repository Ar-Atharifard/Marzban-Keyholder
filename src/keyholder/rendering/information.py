"""A token-protected, script-free usage page; never renders proxy credentials."""

import time
from datetime import UTC, datetime
from html import escape

from keyholder.backends.base import SubscriptionInfo
from keyholder.rendering.profiles import Profile


def byte_count(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"):
        if amount < 1024 or unit == "EiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024
    raise AssertionError("Unreachable")


def information_profile(info: SubscriptionInfo, status: str, now: int | None = None) -> Profile:
    """Return a local-only URI record for clients that ignore subscription metadata."""
    used = info.upload + info.download
    traffic = (
        f"{byte_count(max(0, info.total - used)).upper()} / {byte_count(info.total).upper()} LEFT"
        if info.total
        else "UNLIMITED DATA"
    )
    current = int(time.time()) if now is None else now
    if info.expire:
        seconds = max(0, info.expire - current)
        time_left = "EXPIRED" if seconds == 0 else f"{(seconds + 86399) // 86400}D LEFT"
    else:
        time_left = "AWAITING ACTIVATION" if status == "on_hold" else "NO EXPIRY"
    return Profile(
        kind="tcp_reality",
        name=f"ACCOUNT INFO | {traffic} | {time_left} | DO NOT USE",
        address="127.0.0.1",
        port=1,
        transport="tcp",
        security="none",
        uuid="00000000-0000-4000-8000-000000000000",
        fingerprint="",
    )


def render_information(info: SubscriptionInfo, status: str) -> str:
    used = info.upload + info.download
    remaining = byte_count(max(0, info.total - used)) if info.total else "Unlimited"
    quota = byte_count(info.total) if info.total else "Unlimited"
    if info.expire:
        seconds = max(0, info.expire - int(time.time()))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        left = f"{days} days, {hours} hours, {minutes} minutes"
        expires = datetime.fromtimestamp(info.expire, UTC).strftime("%Y-%m-%d %H:%M UTC")
        if info.expire <= time.time():
            left = "Expired"
    else:
        left = "Awaiting activation" if status == "on_hold" else "No expiry"
        expires = "Not scheduled" if status == "on_hold" else "No expiry"
    rows = [
        ("Account status", status.replace("_", " ").title()),
        ("Traffic remaining", remaining),
        ("Traffic used", byte_count(used)),
        ("Traffic allowance", quota),
        ("Time remaining", left),
        ("Expires", expires),
    ]
    fields = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Subscription status</title>
<style>body{{font:17px system-ui;background:#f5f7fa;color:#152033;margin:0;padding:24px}}
main{{max-width:520px;margin:40px auto;background:white;padding:28px;border-radius:16px}}
h1{{font-size:26px}}dl{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
dt{{color:#526071}}dd{{margin:0;font-weight:600}}small{{color:#526071}}</style>
</head><body><main><h1>Subscription status</h1><dl>{fields}</dl>
<small>Figures reflect the latest account information when this page was loaded.
Refresh to update. Time is shown in UTC.</small></main></body></html>"""
