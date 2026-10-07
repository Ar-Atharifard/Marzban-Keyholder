from typing import Protocol


class UpstreamError(Exception):
    """Sanitized boundary error; never contains upstream response bodies or URLs."""


class UpstreamUnavailable(UpstreamError):
    pass


class BackendAdapter(Protocol):
    async def configurations(self, username: str) -> list[str]: ...
