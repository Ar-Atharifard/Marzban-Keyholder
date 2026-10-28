import argparse
import base64
import io
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from keyholder import billing_cli, cli
from scripts import management_bot
from scripts.admin import worker
from tests.support import ADMIN_KEY


def test_operator_round_trip_and_bot_confirmation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = client.post(
        "/admin/customers",
        headers={"Authorization": "Bearer " + ADMIN_KEY},
        json={"name": "Alice", "upstream_username": "alice"},
    ).json()["customer"]["id"]

    def api(method: str, path: str, body: dict[str, Any] | None = None, **options: Any) -> Any:
        response = client.request(
            method,
            path,
            json=body,
            headers={
                "Authorization": "Bearer " + ADMIN_KEY,
                "Idempotency-Key": options.get("key") or str(uuid4()),
            },
        )
        assert response.status_code < 400, response.text
        return response.json()

    monkeypatch.setattr(worker, "api", api)
    monkeypatch.setattr(worker, "resolve", lambda selector: {"id": cid})
    monkeypatch.setattr(management_bot, "dispatch", worker.execute)
    created = worker.execute(
        "billing-payment-create",
        {
            "customer": "alice",
            "amount": "100",
            "unit": "toman",
            "currency": "IRR",
            "receiving_account": "personal",
            "key": str(uuid4()),
        },
    )
    assert created["amount"] == "1000" and created["status"] == "pending"
    state: dict[str, Any] = {}
    reply = management_bot.command(
        f'/payment confirm {created["id"]} reason="Verified in bank"', state
    )
    assert "Review change" in reply
    assert (
        client.get(
            f"/admin/payments/{created['id']}", headers={"Authorization": "Bearer " + ADMIN_KEY}
        ).json()["status"]
        == "pending"
    )
    confirmation = state["pending"]["code"]
    assert "confirmed" in management_bot.command("/confirm " + confirmation, state)
    assert "1,000 IRR" in management_bot.command("/billing balances alice", {})


def test_cli_payload_preserves_retry_key_and_rejects_unconfirmed_action(tmp_path: Path) -> None:
    parser = cli.parser()
    args = parser.parse_args(
        ["payment", "refund", "payment-id", "--amount", "100", "--reason", "Returned funds"]
    )
    with pytest.raises(ValueError, match="confirm"):
        billing_cli.payload(args)
    args = parser.parse_args(
        [
            "payment",
            "refund",
            "payment-id",
            "--amount",
            "100",
            "--reason",
            "Returned funds",
            "--confirm",
            "--key",
            "retry-key-123456789",
        ]
    )
    value = billing_cli.payload(args)
    assert value["args"]["key"] == "retry-key-123456789"
    assert value["args"]["amount"] == "100"
    path = tmp_path / "receipt.png"
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, "PNG")
    path.write_bytes(image.getvalue())
    args = parser.parse_args(["receipt", "upload", "payment-id", str(path)])
    result = billing_cli.payload(args)
    assert base64.b64decode(result["args"]["content"]) == path.read_bytes()
    assert result["args"]["media_type"] == "image/png"


def test_receipt_download_refuses_overwrite_before_request(tmp_path: Path) -> None:
    output = tmp_path / "image.png"
    output.write_bytes(b"original")
    args = argparse.Namespace(
        operation="billing-receipt-download",
        resource="receipt",
        action="download",
        host="unused",
        local=False,
        output=output,
        key=None,
        id="receipt-id",
    )

    def request(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Existing file must be refused before contacting the server")

    assert billing_cli.run(args, request) == 1
    assert output.read_bytes() == b"original"


def test_receipt_upload_reply_uses_human_format_and_hides_binary_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    import urllib.request

    from keyholder.operator_output import render
    from scripts import billing_bot

    class Opener:
        def open(self, *args: Any, **kwargs: Any) -> io.BytesIO:
            return io.BytesIO(b"synthetic-image")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    state = {
        "receipt_upload": {
            "expires": time.time() + 300,
            "payment_id": "payment-id",
            "key": "retry-key",
        }
    }

    def telegram(*args: Any) -> Any:
        return {"result": {"file_path": "photos/synthetic.png"}}

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        assert operation == "billing-receipt-upload"
        assert base64.b64decode(args["content"]) == b"synthetic-image"
        return {
            "id": "receipt-id",
            "size_bytes": 2048,
            "created_at": "2026-01-01T00:00:00Z",
            "content": "hidden-image",
        }

    text = billing_bot.receive(
        "synthetic",
        {"photo": [{"file_id": "synthetic"}]},
        state,
        telegram,
        dispatch,
        "https://example.invalid",
        render,
    )
    assert "Size: 2.00 KiB" in text and "2026-01-01 00:00:00 UTC" in text
    assert "hidden-image" not in text and "receipt_upload" not in state
