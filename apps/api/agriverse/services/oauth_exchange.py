import json
import secrets
from typing import Any

from redis.asyncio import Redis

from agriverse.config import get_settings

settings = get_settings()


class OAuthExchangeStore:
    def __init__(self) -> None:
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def put(self, payload: dict[str, Any]) -> str:
        code = secrets.token_urlsafe(48)
        await self._redis.setex(f"oauth:exchange:{code}", 60, json.dumps(payload))
        return code

    async def consume(self, code: str) -> dict[str, Any] | None:
        key = f"oauth:exchange:{code}"
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.get(key)
            await pipe.delete(key)
            value, _ = await pipe.execute()
        if value is None:
            return None
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None

    async def close(self) -> None:
        await self._redis.aclose()


oauth_exchange_store = OAuthExchangeStore()
