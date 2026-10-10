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


@pytest.mark.parametrize("body", [[], None, {}, {"access_token": 123}])
def test_malformed_login_is_sanitized(body: object) -> None:
    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            marzban_username=SecretStr("admin"),
            marzban_password=SecretStr("fixture-password"),
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(UpstreamError, match="Upstream authentication failed"):
                await MarzbanBackend(settings, client).configurations("alice")

    asyncio.run(run())


def test_static_token_failure_does_not_attempt_password_login() -> None:
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(401)

    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY), marzban_token=SecretStr("fixture-token")
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(UpstreamError, match="Upstream authentication failed"):
                await MarzbanBackend(settings, client).configurations("alice")

    asyncio.run(run())
    assert paths == ["/api/user/alice"]


def test_concurrent_expired_requests_share_one_token_refresh() -> None:
    logins = 0
    arrived = 0

    async def run() -> None:
        barrier = asyncio.Event()

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal logins, arrived
            if request.url.path == "/api/admin/token":
                logins += 1
                return httpx.Response(200, json={"access_token": f"fixture-token-{logins}"})
            if request.headers["Authorization"] == "Bearer fixture-token-1":
                arrived += 1
                if arrived == 2:
                    barrier.set()
                await barrier.wait()
                return httpx.Response(401)
            return httpx.Response(200, json={"status": "active", "links": [LINK]})

        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            marzban_username=SecretStr("admin"),
            marzban_password=SecretStr("fixture-password"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            backend = MarzbanBackend(settings, client)
            async with asyncio.timeout(2):
                results = await asyncio.gather(
                    backend.configurations("alice"), backend.configurations("bob")
                )
            assert len(results) == 2 and all(result == [LINK] for result in results)

    asyncio.run(run())
    assert logins == 2


def test_response_limit_rejects_oversized_decompressed_body() -> None:
    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY), marzban_token=SecretStr("fixture-token")
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (1048577)))
        ) as client:
            with pytest.raises(UpstreamError, match="Upstream response too large"):
                await MarzbanBackend(settings, client).configurations("alice")

    asyncio.run(run())
