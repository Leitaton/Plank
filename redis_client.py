"""
Plank — Redis client layer.

Provides a lazily-initialized async Redis client (redis.asyncio) plus small
JSON cache helpers. All helpers degrade gracefully: if REDIS_URL is unset or the
server is unreachable, they return None / no-op so the bot keeps working on its
existing in-memory and SQLite paths.
"""

import json
import logging

import redis.asyncio as aioredis

from config import REDIS_URL

log = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_unavailable = False


def _build_client() -> aioredis.Redis | None:
    if not REDIS_URL:
        return None
    return aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
        retry_on_timeout=True,
    )


async def get_redis() -> aioredis.Redis | None:
    """Return a shared async Redis client, or None if Redis is not configured/available."""
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is None:
        _client = _build_client()
        if _client is None:
            _unavailable = True
            return None
    return _client


async def ping() -> bool:
    """True if Redis is configured and responding."""
    client = await get_redis()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception as exc:  # noqa: BLE001 - connectivity is best-effort
        log.warning("Redis ping failed: %s", exc)
        return False


async def cache_get_json(key: str):
    """Return a decoded JSON value for key, or None on miss/error."""
    client = await get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception as exc:  # noqa: BLE001
        log.warning("Redis GET %s failed: %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def cache_set_json(key: str, value, ttl: int | None = None) -> bool:
    """Store value as JSON under key with optional TTL (seconds). Best-effort."""
    client = await get_redis()
    if client is None:
        return False
    try:
        await client.set(key, json.dumps(value), ex=ttl)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Redis SET %s failed: %s", key, exc)
        return False


async def close() -> None:
    """Close the client (call on shutdown)."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None
