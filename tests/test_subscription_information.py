import asyncio
import base64
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from keyholder.backends.base import SubscriptionData, SubscriptionInfo, UpstreamUnavailable
from keyholder.backends.marzban import MarzbanBackend
from keyholder.config import Settings
from keyholder.rendering.information import render_information
from tests.conftest import ADMIN_KEY, LINK, UUID
from tests.test_api import create


@pytest.mark.parametrize("format", ["uri", "xray", "info"])
def test_metadata_and_usage_share_original_token(client: TestClient, format: str) -> None:
    app = cast(FastAPI, client.app)
    registered = create(client)
    info = SubscriptionInfo(0, 1024, 4096, 1893456000)

    class Backend:
        calls = 0

        async def subscription_details(self, username: str) -> SubscriptionData:
            self.calls += 1
            return SubscriptionData([LINK], info=info)

    backend = Backend()
    app.state.backends = {"marzban-default": backend}
    url = "/s/" + str(registered["token"])
    r = client.get(url + "?format=" + format)
    assert r.status_code == 200 and backend.calls == 1
    assert r.headers["subscription-userinfo"] == info.header()
    assert r.headers["cache-control"] == "no-store"
    if format == "info":
        assert "Traffic remaining" in r.text and "3.00 KiB" in r.text
        assert UUID not in r.text and str(registered["token"]) not in r.text
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert "<script" not in r.text
    elif format == "uri":
        links = base64.b64decode(r.text, validate=True).decode().splitlines()
        assert len(links) == 2
        assert links[0].startswith("vless://00000000-0000-4000-8000-000000000000@127.0.0.1:1?")
        assert "ACCOUNT%20INFO" in links[0] and "DO%20NOT%20USE" in links[0]
        assert "@192.0.2.1:9443?" in links[1]
        assert "extra=" not in links[1]
    else:
        assert len(r.json()) == 1
        assert r.json()[0]["outbounds"][0]["settings"]["vnext"][0]["address"] != "127.0.0.1"


def test_limited_account_can_view_information_but_not_configurations(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    registered = create(client)

    class Backend:
        async def subscription_details(self, username: str) -> SubscriptionData:
            return SubscriptionData([LINK], status="limited", info=SubscriptionInfo(0, 10, 8, 1))

    app.state.backends = {"marzban-default": Backend()}
    url = "/s/" + str(registered["token"])
    assert client.get(url).status_code == 404
    r = client.get(url + "?format=info")
    assert r.status_code == 200 and "0.00 B" in r.text and "Expired" in r.text
    assert client.get("/s/invalid?format=info").status_code == 404
    customer = registered["customer"]
    assert isinstance(customer, dict)
    cid = customer["id"]
    disabled = client.patch(
        f"/admin/customers/{cid}",
        json={"status": "disabled"},
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
    )
    assert disabled.status_code == 200
    assert client.get(url + "?format=info").status_code == 404


def test_unknown_usage_is_not_invented(client: TestClient) -> None:
    registered = create(client)
    assert client.get("/s/" + str(registered["token"]) + "?format=info").status_code == 503


def test_information_unlimited_escaped_and_bounded() -> None:
    html = render_information(SubscriptionInfo(0, 5, 0, 0), "<script>alert(1)</script>")
    assert "Unlimited" in html and "No expiry" in html
    assert "<script>" not in html
    with pytest.raises(ValueError):
        SubscriptionInfo(0, -1, 0, 0)
    assert SubscriptionInfo.from_header("upload=0; download=10; total=20; expire=0") == (
        SubscriptionInfo(0, 10, 20, 0)
    )
    for invalid in [
        "upload=0\r\nevil: yes",
        "upload=0; download=1",
        "upload=0; download=-1; total=0; expire=0",
    ]:
        assert SubscriptionInfo.from_header(invalid) is None


def test_marzban_metadata_is_request_local_and_preserves_inactive_contract() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/admin/token":
                return httpx.Response(200, json={"access_token": "synthetic-token"})
            name = request.url.path.rsplit("/", 1)[-1]
            await asyncio.sleep(0)
            return httpx.Response(
                200,
                json={
                    "status": "limited" if name == "limited" else "active",
                    "links": [LINK],
                    "used_traffic": 1 if name == "alice" else 2,
                    "data_limit": 10,
                    "expire": None,
                },
            )

        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            marzban_username=SecretStr("admin"),
            marzban_password=SecretStr("test"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            backend = MarzbanBackend(settings, client)
            a, b = await asyncio.gather(
                backend.subscription_details("alice"), backend.subscription_details("bob")
            )
            assert a.info == SubscriptionInfo(0, 1, 10, 0)
            assert b.info == SubscriptionInfo(0, 2, 10, 0)
            with pytest.raises(UpstreamUnavailable):
                await backend.configurations("limited")
            assert (await backend.subscription_details("limited")).status == "limited"

    asyncio.run(run())


def test_http_provider_keeps_safe_metadata_without_extra_request() -> None:
    from keyholder.backends.subscription import SubscriptionBackend
    from keyholder.config import BackendConfig

    async def run() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                text=LINK,
                headers={
                    "subscription-userinfo": "upload=1; download=2; total=8; expire=0",
                },
            )

        config = BackendConfig(
            id="generic", provider="http_subscription", url="https://provider.example/s/{username}"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            data = await SubscriptionBackend(config, client).subscription_details("alice")
            assert data.links == [LINK] and data.info == SubscriptionInfo(1, 2, 8, 0)
            assert calls == 1

    asyncio.run(run())
