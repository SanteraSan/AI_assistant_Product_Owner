import asyncio

from redis.exceptions import RedisError

from app.services.rate_limiter import RedisRateLimiter


class FakeRedisService:
    def __init__(self) -> None:
        self.count = 0

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        self.count += 1
        return self.count


class FailingRedisService:
    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        raise RedisError("redis unavailable")


def test_redis_rate_limiter_allows_until_limit() -> None:
    limiter = RedisRateLimiter(
        redis_service=FakeRedisService(),  # type: ignore[arg-type]
        limit=2,
        window_seconds=60,
        fail_open=True,
    )

    async def run() -> None:
        first = await limiter.check(scope="chat:test")
        second = await limiter.check(scope="chat:test")
        third = await limiter.check(scope="chat:test")

        assert first.allowed is True
        assert second.allowed is True
        assert third.allowed is False
        assert third.reason == "rate_limited"

    asyncio.run(run())


def test_redis_rate_limiter_fails_open_when_configured() -> None:
    limiter = RedisRateLimiter(
        redis_service=FailingRedisService(),  # type: ignore[arg-type]
        limit=1,
        window_seconds=60,
        fail_open=True,
    )

    async def run() -> None:
        decision = await limiter.check(scope="chat:test")

        assert decision.allowed is True
        assert decision.reason == "redis_error_fail_open"

    asyncio.run(run())
