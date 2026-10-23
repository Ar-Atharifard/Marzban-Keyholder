from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.support import ADMIN_KEY

HEADERS = {"Authorization": "Bearer " + ADMIN_KEY}


def write(client: TestClient, path: str, body: dict[str, Any], key: str | None = None) -> Any:
    return client.post(
        "/admin/" + path, headers={**HEADERS, "Idempotency-Key": key or str(uuid4())}, json=body
    )


def customer(client: TestClient, username: str = "alice") -> str:
    return str(
        client.post(
            "/admin/customers",
            headers=HEADERS,
            json={"name": username, "upstream_username": username},
        ).json()["customer"]["id"]
    )


def payment(client: TestClient, cid: str, amount: str = "1000") -> dict[str, Any]:
    response = write(
        client, "payments", {"customer_id": cid, "amount": amount, "receiving_account": "personal"}
    )
    assert response.status_code == 201, response.text
    row = response.json()
    response = write(
        client, f"payments/{row['id']}/confirm", {"reason": "Verified in bank history"}
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_partial_allocation_refund_and_currency_isolation(client: TestClient) -> None:
    cid = customer(client)
    purchase = write(
        client,
        "purchases",
        {"customer_id": cid, "description": "30 days", "amount": "100", "unit": "toman"},
    ).json()
    p = payment(client, cid, "600")
    a = write(
        client, f"payments/{p['id']}/allocations", {"purchase_id": purchase["id"], "amount": "400"}
    ).json()
    assert (
        client.get(f"/admin/purchases/{purchase['id']}", headers=HEADERS).json()["outstanding"]
        == "600"
    )
    assert (
        write(
            client, f"payments/{p['id']}/refunds", {"amount": "300", "reason": "Refund"}
        ).status_code
        == 409
    )
    assert (
        write(
            client, f"allocations/{a['id']}/reverse", {"reason": "Release for refund"}
        ).status_code
        == 200
    )
    assert (
        write(
            client, f"payments/{p['id']}/refunds", {"amount": "600", "reason": "Full refund"}
        ).status_code
        == 201
    )
    assert (
        write(
            client, f"payments/{p['id']}/refunds", {"amount": "1", "reason": "Too much"}
        ).status_code
        == 409
    )
    crypto = write(
        client,
        "purchases",
        {
            "customer_id": cid,
            "description": "Future crypto price",
            "amount": "1.123456",
            "currency": "USDT",
        },
    ).json()
    assert crypto["amount"] == "1.123456"
    p2 = payment(client, cid)
    assert (
        write(
            client, f"payments/{p2['id']}/allocations", {"purchase_id": crypto["id"], "amount": "1"}
        ).status_code
        == 409
    )
    balances = client.get(f"/admin/customers/{cid}/balances", headers=HEADERS).json()["balances"]
    assert balances["IRR"] == {"outstanding": "1000", "unallocated": "1000"}
    assert balances["USDT"]["outstanding"] == "1.123456"


def test_idempotency_duplicate_references_and_validation(client: TestClient) -> None:
    cid = customer(client)
    body = {
        "customer_id": cid,
        "amount": "1",
        "receiving_account": "personal",
        "reference": "bank-123",
    }
    key = str(uuid4())
    first = write(client, "payments", body, key)
    assert first.status_code == 201
    assert write(client, "payments", body, key).json() == first.json()
    assert write(client, "payments", {**body, "amount": "2"}, key).status_code == 409
    assert write(client, "payments", body).status_code == 409
    for amount in ["1.1", "9223372036854775808"]:
        assert (
            write(client, "payments", {**body, "amount": amount, "reference": None}).status_code
            == 422
        )
    assert write(client, "payments", {**body, "amount": 1.5}).status_code == 422
    assert (
        write(client, "payments", {**body, "received_at": "2026-10-01T12:00:00"}).status_code == 422
    )
    assert client.get("/admin/payments").status_code == 401
    assert client.post("/admin/payments", headers=HEADERS, json=body).status_code == 422


def test_referrals_three_then_two_and_gift_correction(client: TestClient) -> None:
    owner = customer(client, "owner")
    ids, payments = [], []
    for i in range(5):
        cid = customer(client, f"friend_{i}")
        row = write(client, "referrals", {"customer_id": cid, "referrer_id": owner}).json()
        ids.append(row["id"])
        assert not row["eligible"]
        payments.append(payment(client, cid))
    gift = write(
        client,
        "gifts",
        {"referrer_id": owner, "description": "Delivered 10 GB", "referral_ids": ids[:3]},
    ).json()
    available = client.get(
        f"/admin/referrals?referrer_id={owner}&state=eligible", headers=HEADERS
    ).json()
    assert {r["id"] for r in available} == set(ids[3:])
    assert (
        write(
            client, "gifts", {"referrer_id": owner, "description": "Again", "referral_ids": ids[:1]}
        ).status_code
        == 409
    )
    assert (
        write(
            client, f"payments/{payments[0]['id']}/refunds", {"amount": "1000", "reason": "Refund"}
        ).status_code
        == 201
    )
    history = client.get("/admin/gifts", headers=HEADERS).json()
    assert history[0]["qualification_changed"]
    assert (
        write(
            client, f"gifts/{gift['id']}/reverse", {"reason": "Gift entry correction"}
        ).status_code
        == 200
    )
    available = client.get(
        f"/admin/referrals?referrer_id={owner}&state=eligible", headers=HEADERS
    ).json()
    assert len(available) == 4
    assert len(client.get("/admin/billing/actions", headers=HEADERS).json()) > 10


def test_cycles_and_concurrent_gifts(client: TestClient) -> None:
    owner, friend = customer(client, "owner"), customer(client, "friend")
    referral = write(client, "referrals", {"customer_id": friend, "referrer_id": owner}).json()
    assert (
        write(client, "referrals", {"customer_id": owner, "referrer_id": friend}).status_code == 409
    )
    assert (
        write(client, "referrals", {"customer_id": owner, "referrer_id": owner}).status_code == 409
    )
    payment(client, friend)

    def award(_: int) -> int:
        return int(
            write(
                client,
                "gifts",
                {"referrer_id": owner, "description": "Gift", "referral_ids": [referral["id"]]},
            ).status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(award, range(2))) == [201, 409]


def test_void_releases_allocations_but_preserves_history(client: TestClient) -> None:
    cid = customer(client)
    purchase = write(
        client, "purchases", {"customer_id": cid, "description": "Sale", "amount": "1000"}
    ).json()
    p = payment(client, cid)
    write(
        client, f"payments/{p['id']}/allocations", {"purchase_id": purchase["id"], "amount": "1000"}
    )
    assert (
        write(client, f"payments/{p['id']}/void", {"reason": "Wrong customer"}).status_code == 200
    )
    assert (
        client.get(f"/admin/purchases/{purchase['id']}", headers=HEADERS).json()["outstanding"]
        == "1000"
    )
    assert client.get(f"/admin/payments/{p['id']}/allocations", headers=HEADERS).json()[0][
        "reversed_at"
    ]


def test_timezone_normalization_and_referral_date_filter(client: TestClient) -> None:
    owner, friend = customer(client, "owner"), customer(client, "friend")
    row = write(
        client,
        "referrals",
        {"customer_id": friend, "referrer_id": owner, "introduced_at": "2026-10-01T03:30:00+03:30"},
    ).json()
    assert row["introduced_at"] == "2026-10-01T00:00:00+00:00"
    assert (
        client.get(
            "/admin/referrals?since=2026-10-01T00:00:00Z&until=2026-10-02T00:00:00Z",
            headers=HEADERS,
        ).json()[0]["id"]
        == row["id"]
    )
    assert client.get("/admin/referrals?until=2026-10-01T00:00:00Z", headers=HEADERS).json() == []
    assert (
        client.get("/admin/referrals?since=2026-10-01T00:00:00", headers=HEADERS).status_code == 422
    )


def test_void_allows_corrected_bank_reference_without_erasing_original(client: TestClient) -> None:
    cid = customer(client)
    body = {
        "customer_id": cid,
        "amount": "100",
        "receiving_account": "personal",
        "reference": "bank-correction",
    }
    original = write(client, "payments", body).json()
    assert (
        write(client, f"payments/{original['id']}/void", {"reason": "Wrong amount"}).status_code
        == 200
    )
    replacement = write(client, "payments", {**body, "amount": "1000"})
    assert replacement.status_code == 201
    assert replacement.json()["id"] != original["id"]
    assert (
        client.get(f"/admin/payments/{original['id']}", headers=HEADERS).json()["status"] == "void"
    )
