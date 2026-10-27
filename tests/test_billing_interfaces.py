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
    assert "1000" in management_bot.command("/billing balances alice", {})


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
