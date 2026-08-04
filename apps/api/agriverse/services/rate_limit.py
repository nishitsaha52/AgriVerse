from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from redis.asyncio import Redis

from agriverse.config import get_settings
from agriverse.security import Principal

settings = get_settings()

_INCREMENT_WITH_EXPIRY = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RateLimiter:
    def __init__(self) -> None:
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def _increment(self, key: str, seconds: int) -> int:
        result = await self._redis.eval(_INCREMENT_WITH_EXPIRY, 1, key, seconds)
        return int(result)

    async def enforce_request_limits(self, principal: Principal) -> None:
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        try:
            user_count = await self._increment(
                f"rate:user:{principal.user_id}:{minute}",
                90,
            )
            organization_count = await self._increment(
                f"rate:org:{principal.organization_id}:{minute}",
                90,
            )
        except Exception as exc:
            if settings.app_env == "production":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Request limit service unavailable",
                ) from exc
            return
        if user_count > settings.user_requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="User request limit exceeded",
                headers={"Retry-After": "60"},
            )
        if organization_count > settings.organization_requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Organization request limit exceeded",
                headers={"Retry-After": "60"},
            )

    async def enforce_ai_quota(self, principal: Principal) -> None:
        await self.enforce_request_limits(principal)
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        ttl = max(60, int((tomorrow - now).total_seconds()))
        try:
            count = await self._increment(
                f"quota:ai:{principal.organization_id}:{now:%Y%m%d}",
                ttl,
            )
        except Exception as exc:
            if settings.app_env == "production":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="AI quota service unavailable",
                ) from exc
            return
        if count > settings.organization_ai_calls_per_day:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily organization AI quota exceeded",
                headers={"Retry-After": str(ttl)},
            )


rate_limiter = RateLimiter()
