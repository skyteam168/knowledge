import time
from typing import Protocol

from redis.asyncio import Redis


class KeyValueCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, *keys: str) -> None: ...

    async def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Sets the key only if it does not exist; returns whether it was set."""
        ...

    async def pop(self, key: str) -> str | None:
        """Atomic get-and-delete."""
        ...

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        """Atomic increment; `ttl_seconds` is applied when the key is created."""
        ...

    async def llen(self, key: str) -> int: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class RedisCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, url: str) -> "RedisCache":
        return cls(Redis.from_url(url, decode_responses=True))

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return None if value is None else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)

    async def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        return bool(await self._redis.set(key, value, ex=ttl_seconds, nx=True))

    async def pop(self, key: str) -> str | None:
        value = await self._redis.getdel(key)
        return None if value is None else str(value)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        if ttl_seconds is None:
            return int(await self._redis.incr(key))
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl_seconds, nx=True)
            value, _ = await pipe.execute()
        return int(value)

    async def llen(self, key: str) -> int:
        return int(await self._redis.llen(key))

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        await self._redis.aclose()


class MemoryCache:
    """In-process cache for tests and local tooling."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] is not None and item[1] < time.monotonic():
            del self._data[key]
            return False
        return True

    async def get(self, key: str) -> str | None:
        return self._data[key][0] if self._alive(key) else None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires = time.monotonic() + ttl_seconds if ttl_seconds else None
        self._data[key] = (value, expires)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    async def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        if self._alive(key):
            return False
        await self.set(key, value, ttl_seconds)
        return True

    async def pop(self, key: str) -> str | None:
        if not self._alive(key):
            return None
        return self._data.pop(key)[0]

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        if self._alive(key):
            current, expires = int(self._data[key][0]), self._data[key][1]
        else:
            current, expires = 0, time.monotonic() + ttl_seconds if ttl_seconds else None
        self._data[key] = (str(current + 1), expires)
        return current + 1

    async def llen(self, key: str) -> int:
        return 0

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self._data.clear()

    def keys(self) -> list[str]:
        return [k for k in list(self._data) if self._alive(k)]
