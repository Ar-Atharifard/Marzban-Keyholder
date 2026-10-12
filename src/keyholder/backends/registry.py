"""Explicit built-in providers; configuration never imports executable plugins."""

import httpx

from keyholder.backends.base import BackendAdapter
from keyholder.backends.marzban import MarzbanBackend
from keyholder.backends.subscription import SubscriptionBackend
from keyholder.config import BackendConfig, Settings


def backend_configs(settings: Settings) -> list[BackendConfig]:
    if settings.backends:
        return settings.backends
    return [
        BackendConfig(
            id="marzban-default",
            provider="marzban",
            config_ref="default",
            url=settings.marzban_url,
            token=settings.marzban_token,
            username=settings.marzban_username,
            password=settings.marzban_password,
        )
    ]


def build_backends(settings: Settings, client: httpx.AsyncClient) -> dict[str, BackendAdapter]:
    adapters: dict[str, BackendAdapter] = {}
    for spec in backend_configs(settings):
        if spec.provider == "marzban":
            scoped = settings.model_copy(
                update={
                    "marzban_url": spec.url.rstrip("/"),
                    "marzban_token": spec.token,
                    "marzban_username": spec.username,
                    "marzban_password": spec.password,
                }
            )
            adapters[spec.id] = MarzbanBackend(scoped, client)
        else:
            adapters[spec.id] = SubscriptionBackend(spec, client)
    return adapters
