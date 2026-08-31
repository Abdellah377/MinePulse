"""Process-local TTL cache. Not Redis; not shared across workers."""

from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


class TtlCache(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[tuple, tuple[float, T]] = {}
        self._lock = Lock()

    def get(self, key: tuple, *, now: float | None = None) -> T | None:
        stamp = now if now is not None else monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if stamp >= expires_at:
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: T, ttl_seconds: float, *, now: float | None = None) -> None:
        stamp = now if now is not None else monotonic()
        with self._lock:
            self._items[key] = (stamp + max(ttl_seconds, 0), value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


weather_cache: TtlCache = TtlCache()
