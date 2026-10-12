"""Read-only adapter for a trusted HTTP service exporting URI subscriptions."""

import base64
import re
from urllib.parse import quote

import httpx

from keyholder.backends.base import (
    SubscriptionData,
    SubscriptionInfo,
    UpstreamError,
    UpstreamUnavailable,
)
from keyholder.config import BackendConfig


class SubscriptionBackend:
    def __init__(self, config: BackendConfig, client: httpx.AsyncClient) -> None:
        self.config = config
        self.client = client

    async def configurations(self, username: str) -> list[str]:
        return (await self.subscription_details(username)).links

    async def subscription_details(self, username: str) -> SubscriptionData:
        if not re.fullmatch(r"[a-zA-Z0-9_]{3,32}", username):
            raise UpstreamError("Invalid mapping")
        headers = {"Accept": "text/plain"}
        token = self.config.token.get_secret_value()
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            async with self.client.stream(
                "GET",
                self.config.url.replace("{username}", quote(username, safe="")),
                headers=headers,
                follow_redirects=False,
            ) as response:
                if response.status_code in {403, 404, 410}:
                    raise UpstreamUnavailable("Subscription unavailable")
                response.raise_for_status()
                if response.is_redirect:
                    raise UpstreamError("Redirect refused")
                info = SubscriptionInfo.from_header(response.headers.get("subscription-userinfo"))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        raise UpstreamError("Upstream response too large")
            text = body.decode("utf-8").strip()
            if "://" not in text:
                encoded = re.sub(r"\s", "", text)
                text = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                ).decode("utf-8")
            links = [line.strip() for line in text.splitlines() if line.strip()]
            if not links or len(links) > 128 or any(len(link) > 16384 for link in links):
                raise UpstreamError("Invalid subscription body")
            return SubscriptionData(links, info=info)
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise UpstreamError("Upstream request failed") from None
