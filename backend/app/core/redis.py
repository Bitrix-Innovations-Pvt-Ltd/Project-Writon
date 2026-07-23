"""
Redis client with automatic fallback to in-process async store.

- If REDIS_URL is set and reachable  → uses real Redis (production-safe, multi-worker).
- If REDIS_URL is missing/unreachable → falls back to an asyncio-safe in-memory dict
  (fine for single-worker local dev, logs a warning on startup).

Usage anywhere in the app:
    from app.core.redis import cache_get, cache_set, cache_delete
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Try to import redis-py ────────────────────────────────────────────────────
try:
    import redis.asyncio as aioredis  # redis>=4.2 ships with asyncio support
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

# ── Module-level state ────────────────────────────────────────────────────────
_redis_client: Optional[Any] = None          # aioredis.Redis instance (or None)
_memory_store: dict[str, Any] = {}           # fallback in-process store


async def _get_client():
    """Return a connected aioredis client, or None if Redis is not configured."""
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url or not _REDIS_AVAILABLE:
        return None

    try:
        client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()          # fail fast if unreachable
        _redis_client = client
        logger.info("GapFill cache: connected to Redis at %s", redis_url)
    except Exception as exc:
        logger.warning(
            "GapFill cache: Redis unavailable (%s). "
            "Falling back to in-process memory store — "
            "NOT safe for multi-worker deployments.",
            exc,
        )
        _redis_client = None  # remain None → will use memory store

    return _redis_client


# ── Public API ────────────────────────────────────────────────────────────────

async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """
    Persist *value* (JSON-serialisable) under *key*.

    :param key:         Cache key.
    :param value:       Any JSON-serialisable Python object.
    :param ttl_seconds: Expiry (default 1 h).  Ignored by the memory store.
    """
    client = await _get_client()
    serialised = json.dumps(value)

    if client:
        await client.setex(key, ttl_seconds, serialised)
    else:
        _memory_store[key] = value


async def cache_get(key: str) -> Any:
    """Return the value stored under *key*, or ``None`` if absent."""
    client = await _get_client()

    if client:
        raw = await client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    else:
        return _memory_store.get(key)


async def cache_delete(key: str) -> None:
    """Remove *key* from the cache (no-op if it doesn't exist)."""
    client = await _get_client()
    if client:
        await client.delete(key)
    else:
        _memory_store.pop(key, None)
