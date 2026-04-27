from __future__ import annotations

from collections import defaultdict, deque


class LocalRedis:
    """Tiny async Redis-like storage for local single-process development."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self._lists: dict[str, deque[str]] = defaultdict(deque)

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self._kv.get(key)

    async def set(self, key: str, value: str) -> bool:
        self._kv[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._kv:
                del self._kv[key]
                removed += 1
        return removed

    async def lpop(self, key: str) -> str | None:
        bucket = self._lists[key]
        if not bucket:
            return None
        return bucket.popleft()

    async def rpush(self, key: str, *values: str) -> int:
        bucket = self._lists[key]
        bucket.extend(values)
        return len(bucket)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        bucket = list(self._lists[key])
        if not bucket:
            return []
        if stop == -1:
            stop = len(bucket) - 1
        if start < 0:
            start = max(0, len(bucket) + start)
        if stop < 0:
            stop = len(bucket) + stop
        if start > stop:
            return []
        return bucket[start:stop + 1]

    async def lrem(self, key: str, count: int, value: str) -> int:
        bucket = self._lists[key]
        if not bucket:
            return 0
        removed = 0
        items = list(bucket)
        if count == 0:
            kept: list[str] = []
            for item in items:
                if item == value:
                    removed += 1
                    continue
                kept.append(item)
            self._lists[key] = deque(kept)
            return removed

        if count > 0:
            kept: list[str] = []
            for item in items:
                if item == value and removed < count:
                    removed += 1
                    continue
                kept.append(item)
            self._lists[key] = deque(kept)
            return removed

        # count < 0: remove from right
        target = abs(count)
        kept_reversed: list[str] = []
        for item in reversed(items):
            if item == value and removed < target:
                removed += 1
                continue
            kept_reversed.append(item)
        self._lists[key] = deque(reversed(kept_reversed))
        return removed
