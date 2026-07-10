from __future__ import annotations

from dataclasses import dataclass
from time import time

from redis.exceptions import RedisError

from app.services.redis_service import RedisService


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    key: str
    count: int | None
    limit: int
    window_seconds: int
    reason: str


class RedisRateLimiter:
    def __init__(
        self,
        *,
        redis_service: RedisService,
        limit: int,
        window_seconds: int,
        fail_open: bool,
    ) -> None:
        self._redis_service = redis_service
        self._limit = limit
        self._window_seconds = window_seconds
        self._fail_open = fail_open

    async def check(self, *, scope: str) -> RateLimitDecision:
        window = int(time() // self._window_seconds)
        key = f"rate-limit:{scope}:{window}"
        try:
            count = await self._redis_service.increment_with_ttl(
                key=key,
                ttl_seconds=self._window_seconds + 1,
            )
        except RedisError:
            return RateLimitDecision(
                allowed=self._fail_open,
                key=key,
                count=None,
                limit=self._limit,
                window_seconds=self._window_seconds,
                reason="redis_error_fail_open" if self._fail_open else "redis_error",
            )

        return RateLimitDecision(
            allowed=count <= self._limit,
            key=key,
            count=count,
            limit=self._limit,
            window_seconds=self._window_seconds,
            reason="allowed" if count <= self._limit else "rate_limited",
        )
