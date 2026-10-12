from dataclasses import dataclass
from typing import Protocol


class UpstreamError(Exception):
    """Sanitized boundary error; never contains upstream response bodies or URLs."""


class UpstreamUnavailable(UpstreamError):
    pass


@dataclass(frozen=True)
class SubscriptionInfo:
    """Byte counters and Unix expiry; zero quota/expiry means unlimited."""

    upload: int
    download: int
    total: int
    expire: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or not 0 <= v <= 2**63 - 1 for v in vars(self).values()):
            raise ValueError("Invalid subscription information")
        if self.expire > 253402300799:
            raise ValueError("Invalid subscription expiry")

    def header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in vars(self).items())

    @classmethod
    def from_header(cls, value: str | None) -> "SubscriptionInfo | None":
        if not value or len(value) > 256:
            return None
        fields: dict[str, int] = {}
        try:
            for item in value.split(";"):
                key, raw = (p.strip() for p in item.split("=", 1))
                if key not in {"upload", "download", "total", "expire"}:
                    continue
                if key in fields or not raw.isascii() or not raw.isdecimal():
                    return None
                fields[key] = int(raw)
            if set(fields) != {"upload", "download", "total", "expire"}:
                return None
            return cls(**fields)
        except (ValueError, TypeError):
            return None


@dataclass(frozen=True, repr=False)
class SubscriptionData:
    links: list[str]
    status: str = "active"
    info: SubscriptionInfo | None = None


class BackendAdapter(Protocol):
    async def configurations(self, username: str) -> list[str]: ...
