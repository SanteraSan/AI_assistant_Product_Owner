from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RedisService:
    def __init__(self, url: str) -> None:
        self._client = Redis.from_url(url, decode_responses=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        async with self._client.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, ttl_seconds)
            result = await pipeline.execute()
        return int(result[0])
