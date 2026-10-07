import asyncio

import httpx
import pytest
from pydantic import SecretStr

from keyholder.backends.base import UpstreamError, UpstreamUnavailable
from keyholder.backends.marzban import MarzbanBackend
from keyholder.config import Settings
from tests.conftest import ADMIN_KEY, LINK


def test_login_and_read_only_mapping() -> None:
    paths = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/admin/token":
            assert b"username=admin" in request.content
            return httpx.Response(200, json={"access_token": "bearer-secret"})
        assert request.headers["Authorization"] == "Bearer bearer-secret"
        return httpx.Response(
            200,
            json={
                "status": "active",
                "links": [LINK],
                "subscription_url": "http://evil.invalid/secret",
            },
        )

    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            marzban_url="https://panel.example",
            marzban_username=SecretStr("admin"),
            marzban_password=SecretStr("password"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            backend = MarzbanBackend(settings, client)
            assert await backend.configurations("alice") == [LINK]
            assert await backend.configurations("bob") == [LINK]

    asyncio.run(run())
    assert paths == [
        ("POST", "/api/admin/token"),
        ("GET", "/api/user/alice"),
        ("GET", "/api/user/bob"),
    ]


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {"secret": "upstream-secret"}),
        (302, {}),
        (200, {"status": "active"}),
        (200, {"status": "disabled", "links": []}),
        (200, {"status": "active", "links": ["x"] * 129}),
    ],
)
def test_upstream_failures_sanitized(status: int, body: dict[str, object]) -> None:
    async def run() -> None:
        settings = Settings(admin_key=SecretStr(ADMIN_KEY), marzban_token=SecretStr("secret"))
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
        ) as client:
            backend = MarzbanBackend(settings, client)
            with pytest.raises((UpstreamError, UpstreamUnavailable)) as exc:
                await backend.configurations("alice")
            assert "upstream-secret" not in str(exc.value)

    asyncio.run(run())


def test_expired_token_refresh() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("token"):
            calls += 1
            return httpx.Response(200, json={"access_token": str(calls)})
        if calls == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"status": "active", "links": [LINK]})

    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            marzban_username=SecretStr("admin"),
            marzban_password=SecretStr("pass"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            assert await MarzbanBackend(settings, client).configurations("alice") == [LINK]

    asyncio.run(run())
    assert calls == 2
