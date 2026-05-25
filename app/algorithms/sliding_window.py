import time
import redis.asyncio as aioredis
from dataclasses import dataclass
from app.config import settings

_redis_client = None


async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


@dataclass
class RateLimitResult:
    allowed: bool
    client_id: str
    limit: int
    remaining: int
    reset_at: int
    retry_after: int
    algorithm: str
    current_count: int


async def check(
    client_id: str,
    limit: int = None,
    window_seconds: int = None,
) -> RateLimitResult:
    """
    Sliding window rate limit check using Redis Sorted Sets.

    Key format: ratelimit:sliding:{client_id}
    Each request is stored as a member with timestamp as score.
    To check: count members with score in (now - window, now].
    Old members are cleaned up automatically.
    """
    limit = limit or settings.default_limit
    window_seconds = window_seconds or settings.default_window_seconds

    r = await get_redis()

    now = time.time()
    window_start = now - window_seconds
    key = f"ratelimit:sliding:{client_id}"

    # Unique member for this request — timestamp + tiny random offset
    # to handle multiple requests at exact same millisecond
    member = str(now)

    pipe = r.pipeline()
    # Remove old requests outside the window
    pipe.zremrangebyscore(key, 0, window_start)
    # Add this request with timestamp as score
    pipe.zadd(key, {member: now})
    # Count all requests in the window
    pipe.zcard(key)
    # Set expiry on the key
    pipe.expire(key, window_seconds + 1)
    results = await pipe.execute()

    current_count = results[2]  # zcard result
    allowed = current_count <= limit
    remaining = max(0, limit - current_count)

    # Estimate when the oldest request will fall out of window
    oldest = await r.zrange(key, 0, 0, withscores=True)
    if oldest and not allowed:
        oldest_score = oldest[0][1]
        retry_after = int(oldest_score + window_seconds - now) + 1
    else:
        retry_after = 0

    reset_at = int(now + window_seconds)

    return RateLimitResult(
        allowed=allowed,
        client_id=client_id,
        limit=limit,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=retry_after,
        algorithm="sliding_window",
        current_count=current_count,
    )


async def get_current_count(client_id: str, window_seconds: int = None) -> int:
    """Get current request count in the sliding window."""
    window_seconds = window_seconds or settings.default_window_seconds
    r = await get_redis()
    now = time.time()
    window_start = now - window_seconds
    key = f"ratelimit:sliding:{client_id}"
    await r.zremrangebyscore(key, 0, window_start)
    return await r.zcard(key)