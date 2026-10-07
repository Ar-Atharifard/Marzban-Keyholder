import time
from collections import OrderedDict
from typing import Protocol


class RateLimiter(Protocol):
    def allow(self, key: str) -> bool: ...


class MemoryRateLimiter:
    """Single-worker fixed windows; replace with Redis for multiple workers/replicas."""

    def __init__(self, limit: int, max_keys: int = 10000) -> None:
        self.limit = limit
        self.max_keys = max_keys
        self.windows: OrderedDict[str, tuple[int, int]] = OrderedDict()

    def allow(self, key: str) -> bool:
        window = int(time.monotonic() // 60)
        previous, count = self.windows.get(key, (window, 0))
        count = count + 1 if previous == window else 1
        self.windows[key] = (window, count)
        self.windows.move_to_end(key)
        if len(self.windows) > self.max_keys:
            self.windows.popitem(last=False)
        return count <= self.limit
