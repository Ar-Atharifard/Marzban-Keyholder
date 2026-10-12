import asyncio
import base64
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from keyholder.backends.base import UpstreamError, UpstreamUnavailable
from keyholder.backends.registry import build_backends
from keyholder.backends.subscription import SubscriptionBackend
from keyholder.config import BackendConfig, Settings
from keyholder.main import create_app
from keyholder.models import Backend, Base
from keyholder.rendering.profiles import allowed_cdn, normalize
from tests.conftest import ADMIN_KEY, LINK, UUID


def test_multiple_panels_keep_credentials_and_urls_separate() -> None:
    seen: list[tuple[str, str]] = []

    def handle(r: httpx.Request) -> httpx.Response:
        seen.append((r.url.host, r.headers["authorization"]))
        return httpx.Response(200, json={"status": "active", "links": [LINK]})

    async def run() -> None:
        settings = Settings(
            admin_key=SecretStr(ADMIN_KEY),
            backends=[
                BackendConfig(
                    id="east", url="https://east.example", token=SecretStr("synthetic-east")
                ),
                BackendConfig(
                    id="west", url="https://west.example", token=SecretStr("synthetic-west")
                ),
            ],
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            adapters = build_backends(settings, c)
            assert await adapters["east"].configurations("alice") == [LINK]
            assert await adapters["west"].configurations("alice") == [LINK]

    asyncio.run(run())
    assert seen == [
        ("east.example", "Bearer synthetic-east"),
        ("west.example", "Bearer synthetic-west"),
    ]


@pytest.mark.parametrize("encoded", [False, True])
def test_subscription_provider_serves_registered_identity_without_marzban(
    tmp_path: Path,
    encoded: bool,
) -> None:
    config = BackendConfig(
        id="source", provider="http_subscription", url="https://source.example/{username}"
    )
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        backends=[config],
        profile_source="upstream",
        token_encryption_key=SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()),
        database_url=f"sqlite:///{tmp_path}/app.db",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    calls: list[str] = []

    def handle(r: httpx.Request) -> httpx.Response:
        calls.append(str(r.url))
        return httpx.Response(
            200, content=base64.b64encode(LINK.encode()) if encoded else LINK.encode()
        )

    with TestClient(app) as client:
        transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        app.state.backends = {"source": SubscriptionBackend(config, transport)}
        headers = {"Authorization": "Bearer " + ADMIN_KEY}
        assert client.post("/admin/backends/register", headers=headers).status_code == 200
        response = client.post(
            "/admin/customers",
            headers=headers,
            json={"name": "Alice", "backend_id": "source", "upstream_username": "alice"},
        )
        assert response.status_code == 201
        token = response.json()["token"]
        assert client.get("/s/" + token).status_code == 200
        repeated = client.post(
            "/admin/customers",
            headers=headers,
            json={"name": "Again", "backend_id": "source", "upstream_username": "alice"},
        )
        assert repeated.json()["token"] == token
        asyncio.run(transport.aclose())
    assert calls == ["https://source.example/alice"]


@pytest.mark.parametrize("status", [302, 403, 404, 410, 500])
def test_subscription_errors_and_redirects_are_sanitized(status: int) -> None:
    async def run() -> None:
        config = BackendConfig(
            id="source",
            provider="http_subscription",
            url="https://source.example/{username}",
            token=SecretStr("synthetic-bearer"),
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    status,
                    headers={"location": "https://evil.example"},
                    text="private upstream response",
                )
            )
        ) as c:
            with pytest.raises(
                UpstreamUnavailable if status in [403, 404, 410] else UpstreamError
            ) as e:
                await SubscriptionBackend(config, c).configurations("alice")
            assert "private" not in str(e.value) and "synthetic" not in str(e.value)

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "https://{username}.example/sub",
        "https://source.example/{username!r}",
        "https://source.example/no-placeholder",
        "https://user:password@source.example/{username}",
        "https://source.example/{username}#secret",
    ],
)
def test_config_cannot_move_source_host_or_embed_userinfo(url: str) -> None:
    with pytest.raises(ValidationError):
        BackendConfig(id="source", provider="http_subscription", url=url)


def test_duplicate_backend_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            admin_key=SecretStr(ADMIN_KEY),
            backends=[
                BackendConfig(id="same", url="https://one.example"),
                BackendConfig(id="same", url="https://two.example"),
            ],
        )


def test_registered_backend_provider_cannot_be_silently_replaced(tmp_path: Path) -> None:
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        database_url=f"sqlite:///{tmp_path}/app.db",
        backends=[
            BackendConfig(
                id="source", provider="http_subscription", url="https://source.example/{username}"
            )
        ],
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as db:
        db.add(Backend(id="source", provider="marzban", config_ref="default"))
        db.commit()
    with pytest.raises(RuntimeError, match="identity differs"), TestClient(app):
        pass


def test_custom_cdn_network_requires_explicit_tls_and_http_identity() -> None:
    link = f"vless://{UUID}@192.0.2.5:443?type=ws&security=tls&sni=edge.example&host=edge.example&path=%2Fx"
    assert normalize(link) is None
    p = normalize(link, ("192.0.2.0/24",))
    assert p is not None
    assert not allowed_cdn(p, (), ("192.0.2.0/24",))
    assert not allowed_cdn(p, ("different.example",), ("192.0.2.0/24",))
    assert allowed_cdn(p, ("edge.example",), ("192.0.2.0/24",))


def test_backend_registration_does_not_reveal_credentials(tmp_path: Path) -> None:
    secret = "synthetic-do-not-expose"
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        database_url=f"sqlite:///{tmp_path}/app.db",
        backends=[
            BackendConfig(id="other", url="https://private-source.example", token=SecretStr(secret))
        ],
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.get("/admin/backends").status_code == 401
        h = {"Authorization": "Bearer " + ADMIN_KEY}
        for _ in range(2):
            r = c.post("/admin/backends/register", headers=h)
            assert r.status_code == 200
            assert secret not in r.text and "private-source" not in r.text
            assert r.json() == [
                {"id": "other", "provider": "marzban", "config_ref": "default", "registered": True}
            ]


@pytest.mark.parametrize("body", [b"not base64", b"", b"x" * (1024 * 1024 + 1)])
def test_http_source_rejects_malformed_and_oversized_bodies(body: bytes) -> None:
    async def run() -> None:
        config = BackendConfig(
            id="source", provider="http_subscription", url="https://source.example/{username}"
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
        ) as client:
            with pytest.raises(UpstreamError):
                await SubscriptionBackend(config, client).configurations("alice")

    asyncio.run(run())


def test_empty_deployment_profile_set_disables_subscription(client: TestClient) -> None:
    from typing import cast

    from fastapi import FastAPI

    from tests.test_api import create

    app = cast(FastAPI, client.app)
    token = str(create(client)["token"])
    app.state.settings.enabled_profiles = ()
    assert client.get("/s/" + token).status_code == 503


def test_configuration_errors_do_not_include_credentials() -> None:
    secret = "synthetic-sensitive-value"
    with pytest.raises(ValidationError) as error:
        Settings.model_validate(
            {
                "admin_key": ADMIN_KEY,
                "backends": [
                    {
                        "id": "source",
                        "provider": "unknown",
                        "url": "https://source.example",
                        "token": secret,
                    }
                ],
            }
        )
    assert secret not in str(error.value)
