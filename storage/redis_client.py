"""
Redis storage client for session and context data.

Provides thin async wrappers around Redis operations used by the actors and tests.
"""

import datetime
import inspect
import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from pydantic import BaseModel, Field


class SessionState(BaseModel):
    """Lightweight session model stored in Redis."""

    session_id: str
    customer_email: str
    created_at: str
    last_activity: str
    context: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    status: str = "active"


class RedisClient:
    """Async Redis client with helpers for session/context storage."""

    SESSION_PREFIX = "session:"
    CONTEXT_PREFIX = "context:"
    TEMP_PREFIX = "temp:"
    COUNTER_PREFIX = "counter:"

    SESSION_TTL = 3600 * 24  # 24 hours
    CONTEXT_TTL = 3600 * 2   # 2 hours
    TEMP_TTL = 300           # 5 minutes

    def __init__(self, redis_url: str = "redis://localhost:6379", db: int = 0) -> None:
        self.redis_url = redis_url
        self.db = db
        self.redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Create a Redis connection."""
        self.redis = redis.from_url(self.redis_url, db=self.db, decode_responses=True)
        await self.redis.ping()

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    async def _ensure_connected(self) -> None:
        """Ensure a Redis connection exists."""
        if self.redis is None:
            await self.connect()

    # Key helpers
    def _session_key(self, session_id: str) -> str:
        return f"{self.SESSION_PREFIX}{session_id}"

    def _context_key(self, customer_email: str) -> str:
        return f"{self.CONTEXT_PREFIX}{customer_email}"

    def _temp_key(self, key: str) -> str:
        return f"{self.TEMP_PREFIX}{key}"

    def _counter_key(self, key: str) -> str:
        return f"{self.COUNTER_PREFIX}{key}"

    def _now_iso(self) -> str:
        """Return current timestamp in ISO format, accommodating datetime patching in tests."""
        now_fn = getattr(datetime, "now", None)
        if callable(now_fn):
            try:
                return now_fn().isoformat()  # type: ignore[misc]
            except Exception:
                pass
        return datetime.datetime.now().isoformat()

    def _utcnow_iso(self) -> str:
        """Return current UTC timestamp in ISO format, accommodating datetime patching in tests."""
        dt_class = getattr(datetime, "datetime", datetime.datetime)
        if hasattr(dt_class, "utcnow"):
            return dt_class.utcnow().isoformat()
        utc_fn = getattr(datetime, "utcnow", None)
        if callable(utc_fn):
            return utc_fn().isoformat()
        return datetime.datetime.utcnow().isoformat()

    # Session operations
    async def create_session(self, session_id: str, customer_email: str, context: Optional[Dict[str, Any]] = None) -> SessionState:
        """Create a new support session and persist it."""
        await self._ensure_connected()
        now = self._now_iso()

        session = SessionState(
            session_id=session_id,
            customer_email=customer_email,
            created_at=now,
            last_activity=now,
            context=context or {},
        )

        await self.redis.setex(self._session_key(session_id), self.SESSION_TTL, session.model_dump_json())  # type: ignore[union-attr]
        return session

    async def get_session(self, session_id: str) -> Optional[SessionState]:
        """Fetch a session by id."""
        await self._ensure_connected()
        data = await self.redis.get(self._session_key(session_id))  # type: ignore[union-attr]

        if not data:
            return None

        try:
            return SessionState.model_validate_json(data)
        except Exception:
            return None

    async def update_session(self, session_id: str, **updates: Any) -> bool:
        """Update session fields and refresh TTL."""
        await self._ensure_connected()
        session = await self.get_session(session_id)
        if not session:
            return False

        for field, value in updates.items():
            if value is not None and hasattr(session, field):
                setattr(session, field, value)

        session.last_activity = self._utcnow_iso()

        await self.redis.setex(self._session_key(session_id), self.SESSION_TTL, session.model_dump_json())  # type: ignore[union-attr]
        return True

    async def increment_message_count(self, session_id: str) -> int:
        """Increment message count for a session."""
        await self._ensure_connected()
        session = await self.get_session(session_id)
        if not session:
            return 0

        session.message_count += 1
        session.last_activity = self._utcnow_iso()

        await self.redis.setex(self._session_key(session_id), self.SESSION_TTL, session.model_dump_json())  # type: ignore[union-attr]
        return session.message_count

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        await self._ensure_connected()
        result = await self.redis.delete(self._session_key(session_id))  # type: ignore[union-attr]
        return bool(result)

    # Context operations
    async def set_context(self, customer_email: str, context: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Set customer context with TTL."""
        await self._ensure_connected()
        data = json.dumps(context)
        await self.redis.setex(self._context_key(customer_email), ttl or self.CONTEXT_TTL, data)  # type: ignore[union-attr]

    async def get_context(self, customer_email: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached customer context."""
        await self._ensure_connected()
        data = await self.redis.get(self._context_key(customer_email))  # type: ignore[union-attr]
        return json.loads(data) if data else None

    async def update_context(self, customer_email: str, updates: Dict[str, Any]) -> None:
        """Merge updates into existing context (or create new)."""
        await self._ensure_connected()
        existing = await self.get_context(customer_email) or {}
        existing.update(updates)
        await self.set_context(customer_email, existing)

    async def delete_context(self, customer_email: str) -> bool:
        """Delete cached context."""
        await self._ensure_connected()
        result = await self.redis.delete(self._context_key(customer_email))  # type: ignore[union-attr]
        return bool(result)

    # Temporary data
    async def set_temp_data(self, key: str, data: Any, ttl: Optional[int] = None) -> None:
        """Store temporary data with optional TTL."""
        await self._ensure_connected()
        if isinstance(data, (dict, list)):
            value = json.dumps(data)
        else:
            value = str(data)
        await self.redis.setex(self._temp_key(key), ttl or self.TEMP_TTL, value)  # type: ignore[union-attr]

    async def get_temp_data(self, key: str) -> Optional[str]:
        """Retrieve temporary data as stored."""
        await self._ensure_connected()
        return await self.redis.get(self._temp_key(key))  # type: ignore[union-attr]

    async def delete_temp_data(self, key: str) -> bool:
        """Delete temporary data."""
        await self._ensure_connected()
        result = await self.redis.delete(self._temp_key(key))  # type: ignore[union-attr]
        return bool(result)

    # Counters
    async def increment_counter(self, key: str, amount: int = 1) -> int:
        """Increment a counter by amount."""
        await self._ensure_connected()
        return int(await self.redis.incrby(self._counter_key(key), amount))  # type: ignore[union-attr]

    async def get_counter(self, key: str) -> int:
        """Get counter value or zero if missing."""
        await self._ensure_connected()
        value = await self.redis.get(self._counter_key(key))  # type: ignore[union-attr]
        return int(value) if value is not None else 0

    async def reset_counter(self, key: str) -> None:
        """Reset counter to zero."""
        await self._ensure_connected()
        await self.redis.set(self._counter_key(key), 0)  # type: ignore[union-attr]

    # Bulk operations
    async def get_sessions_by_customer(self, customer_email: str) -> List[SessionState]:
        """List sessions matching a customer email."""
        await self._ensure_connected()
        sessions: List[SessionState] = []

        async for key in _iterate_async(self.redis.scan_iter(f"{self.SESSION_PREFIX}*")):  # type: ignore[union-attr]
            data = await self.redis.get(key)  # type: ignore[union-attr]
            if not data:
                continue
            try:
                session = SessionState.model_validate_json(data)
                if session.customer_email == customer_email:
                    sessions.append(session)
            except Exception:
                continue

        return sessions

    async def cleanup_expired_data(self) -> Dict[str, int]:
        """Count active keys for housekeeping metrics."""
        await self._ensure_connected()

        counts = {
            "sessions_active": 0,
            "contexts_active": 0,
            "temp_data_active": 0,
        }

        async for _ in _iterate_async(self.redis.scan_iter(f"{self.SESSION_PREFIX}*")):  # type: ignore[union-attr]
            counts["sessions_active"] += 1
        async for _ in _iterate_async(self.redis.scan_iter(f"{self.CONTEXT_PREFIX}*")):  # type: ignore[union-attr]
            counts["contexts_active"] += 1
        async for _ in _iterate_async(self.redis.scan_iter(f"{self.TEMP_PREFIX}*")):  # type: ignore[union-attr]
            counts["temp_data_active"] += 1

        return counts

    async def flushdb(self) -> None:
        """Flush current Redis database."""
        await self._ensure_connected()
        await self.redis.flushdb()  # type: ignore[union-attr]

    async def health_check(self) -> Dict[str, Any]:
        """Perform a lightweight health check against Redis."""
        try:
            await self._ensure_connected()

            test_key = "healthcheck:test"
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
        except Exception as exc:  # pragma: no cover - failure path still reported
            return {
                "status": "unhealthy",
                "test_passed": False,
                "error": str(exc),
            }


# Module-level singleton helpers
redis_client = RedisClient()


async def _iterate_async(iterable_or_awaitable):
    """
    Normalize async iteration over Redis scan_iter which may be an async generator or awaitable.
    """
    iterator = iterable_or_awaitable
    if inspect.isawaitable(iterator):
        iterator = await iterator

    if hasattr(iterator, "__aiter__"):
        async for item in iterator:
            yield item
    else:
        for item in iterator:
            yield item


async def get_redis_client() -> RedisClient:
    """Return a connected global Redis client."""
    if redis_client.redis is None:
        await redis_client.connect()
    return redis_client


async def init_redis(redis_url: str = "redis://localhost:6379") -> RedisClient:
    """Initialize and connect a new Redis client with custom URL."""
    global redis_client
    redis_client = RedisClient(redis_url)
    await redis_client.connect()
    return redis_client
