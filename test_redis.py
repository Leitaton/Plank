"""
Standalone Redis integration test for Plank.

Run:  python test_redis.py
Requires REDIS_URL to be set (via .env or environment).
Exits non-zero on any failure.
"""

import asyncio
import sys

import redis_client
from config import REDIS_URL


async def main() -> int:
    if not REDIS_URL:
        print("FAIL: REDIS_URL is not set (check your .env)")
        return 1

    # 1) Connectivity
    if not await redis_client.ping():
        print("FAIL: ping returned False — cannot reach Redis")
        return 1
    print("PASS: ping")

    # 2) JSON round-trip with TTL
    key = "plankk:test:obj"
    payload = {"hello": "world", "n": 42}
    assert await redis_client.cache_set_json(key, payload, ttl=60), "set failed"
    got = await redis_client.cache_get_json(key)
    assert got == payload, f"round-trip mismatch: {got!r}"
    print("PASS: json set/get round-trip")

    # 3) Miss returns None
    assert await redis_client.cache_get_json("plankk:test:missing") is None
    print("PASS: miss returns None")

    # 4) lookup_bin reads through Redis (deterministic — no external API needed)
    from utils import helpers

    client = await redis_client.get_redis()
    seeded = {
        "scheme": "VISA", "type": "CREDIT", "brand": "SIGNATURE",
        "bank": "TEST BANK", "country": "UNITED STATES", "country_emoji": "🇺🇸",
    }
    await redis_client.cache_set_json("bin:457173", seeded, ttl=60)
    helpers._bin_cache.clear()  # force the in-memory cache to miss -> must hit Redis

    result = await helpers.lookup_bin("4571736382716483")
    assert result == seeded, f"read-through failed, got {result!r}"
    assert helpers._bin_cache.get("457173") == seeded, "in-memory cache not warmed from Redis"
    print(f"PASS: lookup_bin read-through Redis -> scheme={result['scheme']} country={result['country']}")

    # 5) Live write path (best-effort; skipped if external BIN API is unreachable)
    await client.delete("bin:411111")
    helpers._bin_cache.clear()
    live = await helpers.lookup_bin("4111111111111111")
    if live.get("scheme") not in (None, "N/A"):
        assert await redis_client.cache_get_json("bin:411111") == live
        print(f"PASS: live lookup cached -> scheme={live['scheme']}")
    else:
        print("SKIP: live BIN API unreachable in this environment (fallback returned)")

    # cleanup
    await client.delete(key, "bin:457173", "bin:411111")
    if helpers._bin_session and not helpers._bin_session.closed:
        await helpers._bin_session.close()
    await redis_client.close()
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
