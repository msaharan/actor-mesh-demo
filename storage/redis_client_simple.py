"""
Simplified Redis client focused on customer context caching.
"""

import json
from typing import Any, Dict, Optional

import redis.asyncio as redis


class SimplifiedRedisClient:
    """Minimal Redis helper used by the ContextRetriever actor."""

    CONTEXT_PREFIX = "context:"
    CONTEXT_TTL = 3600 * 2  # 2 hours

    def __init__(self, redis_url: str = "redis://localhost:6379", db: int = 0) -> None:
        self.redis_url = redis_url
        self.db = db
        self.redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish a Redis connection."""
        self.redis = redis.from_url(self.redis_url, db=self.db, decode_responses=True)
        await self.redis.ping()

    async def disconnect(self) -> None:
        """Close connection."""
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    async def _ensure_connected(self) -> None:
        """Connect if not already connected."""
        if self.redis is None:
            await self.connect()

    def _context_key(self, customer_email: str) -> str:
        return f"{self.CONTEXT_PREFIX}{customer_email}"

    async def cache_customer_context(self, customer_email: str, context_data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache customer context JSON."""
        await self._ensure_connected()
        data = json.dumps(context_data)
        await self.redis.setex(self._context_key(customer_email), ttl or self.CONTEXT_TTL, data)  # type: ignore[union-attr]

    async def get_customer_context(self, customer_email: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached customer context if available."""
        await self._ensure_connected()
        raw = await self.redis.get(self._context_key(customer_email))  # type: ignore[union-attr]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            await self.redis.delete(self._context_key(customer_email))  # type: ignore[union-attr]
            return None

    async def update_customer_context(self, customer_email: str, updates: Dict[str, Any]) -> bool:
        """Merge updates into cached context."""
        await self._ensure_connected()
        existing = await self.get_customer_context(customer_email)
        if existing is None:
            return False

        existing.update(updates)
        await self.cache_customer_context(customer_email, existing)
        return True

    async def invalidate_customer_context(self, customer_email: str) -> bool:
        """Remove cached context."""
        await self._ensure_connected()
        result = await self.redis.delete(self._context_key(customer_email))  # type: ignore[union-attr]
        return bool(result)

    async def health_check(self) -> Dict[str, Any]:
        """Perform a basic Redis health check."""
        try:
            await self._ensure_connected()

            test_key = "healthcheck:simple"
            await self.redis.set(test_key, "ok")  # type: ignore[union-attr]
            test_value = await self.redis.get(test_key)  # type: ignore[union-attr]
            await self.redis.delete(test_key)  # type: ignore[union-attr]

            info = await self.redis.info()  # type: ignore[union-attr]

            return {
                "status": "healthy",
                "test_passed": test_value == "ok",
                "connected_clients": info.get("connected_clients"),
                "used_memory": info.get("used_memory_human") or info.get("used_memory"),
                "uptime": info.get("uptime_in_seconds"),
            }
        except Exception as exc:  # pragma: no cover - failure path recorded
            return {
                "status": "unhealthy",
                "test_passed": False,
                "error": str(exc),
            }


# Module-level singleton helpers
simplified_redis_client = SimplifiedRedisClient()


async def get_simplified_redis_client() -> SimplifiedRedisClient:
    """Return a connected simplified Redis client."""
    if simplified_redis_client.redis is None:
        await simplified_redis_client.connect()
    return simplified_redis_client


async def init_simplified_redis(redis_url: str = "redis://localhost:6379") -> SimplifiedRedisClient:
    """Initialize a new simplified client with custom URL."""
    global simplified_redis_client
    simplified_redis_client = SimplifiedRedisClient(redis_url)
    await simplified_redis_client.connect()
    return simplified_redis_client

