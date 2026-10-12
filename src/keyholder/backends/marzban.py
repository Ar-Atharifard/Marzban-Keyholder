import asyncio
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from keyholder.backends.base import (
    SubscriptionData,
    SubscriptionInfo,
    UpstreamError,
    UpstreamUnavailable,
)
from keyholder.config import Settings


class UserResponse(BaseModel):
    status: str
    links: list[str] = Field(max_length=128)
    used_traffic: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)
    data_limit: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)
    expire: int | None = Field(default=None, ge=0, le=253402300799, strict=True)


class MarzbanBackend:
    """Read-only adapter. Verify this contract against installed Marzban OpenAPI."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.token = settings.marzban_token.get_secret_value()
        self.lock = asyncio.Lock()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with self.client.stream(method, self.settings.marzban_url + path, **kwargs) as r:
                r.raise_for_status()
                chunks = bytearray()
                async for chunk in r.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 1024 * 1024:
                        raise UpstreamError("Upstream response too large")
                return httpx.Response(r.status_code, content=bytes(chunks))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise PermissionError from None
            raise UpstreamError("Upstream request failed") from None
        except httpx.HTTPError:
            raise UpstreamError("Upstream unavailable") from None

    async def login(self) -> None:
        async with self.lock:
            if self.token:
                return
            if (
                not self.settings.marzban_username.get_secret_value()
                or not self.settings.marzban_password.get_secret_value()
            ):
                raise UpstreamError("Upstream credentials not configured")
            try:
                r = await self.request(
                    "POST",
                    "/api/admin/token",
                    data={
                        "username": self.settings.marzban_username.get_secret_value(),
                        "password": self.settings.marzban_password.get_secret_value(),
                    },
                )
                data = r.json()
                if not isinstance(data, dict):
                    raise ValueError
                token = data.get("access_token")
                if not isinstance(token, str) or not token or len(token) > 16384:
                    raise ValueError
                self.token = token
            except (ValueError, PermissionError):
                raise UpstreamError("Upstream authentication failed") from None

    async def configurations(self, username: str) -> list[str]:
        data = await self.subscription_details(username)
        if data.status != "active":
            raise UpstreamUnavailable("Upstream user inactive")
        return data.links

    async def subscription_details(self, username: str) -> SubscriptionData:
        if not re.fullmatch(r"[a-zA-Z0-9_]{3,32}", username):
            raise UpstreamError("Invalid mapping")
        await self.login()
        for attempt in range(2):
            try:
                used_token = self.token
                r = await self.request(
                    "GET",
                    f"/api/user/{username}",
                    headers={"Authorization": f"Bearer {used_token}"},
                )
                user = UserResponse.model_validate(r.json())
                info = None
                if (
                    user.used_traffic is not None
                    and {"data_limit", "expire"} <= user.model_fields_set
                ):
                    info = SubscriptionInfo(
                        0, user.used_traffic, user.data_limit or 0, user.expire or 0
                    )
                return SubscriptionData(user.links, user.status, info)
            except PermissionError:
                if attempt or self.settings.marzban_token.get_secret_value():
                    raise UpstreamError("Upstream authentication failed") from None
                if self.token == used_token:
                    self.token = ""
                await self.login()
            except (ValueError, ValidationError):
                raise UpstreamError("Upstream schema mismatch") from None
        raise UpstreamError("Upstream authentication failed")
