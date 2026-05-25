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
    reset_at: int        # Unix timestamp when window resets
    retry_after: int     # Seconds to wait if blocked
    algorithm: str
    current_count: int


async def check(
    client_id: str,
    limit: int = None,
    window_seconds: int = None,
) -> RateLimitResult:
    """
    Fixed window rate limit check.

    Key format: ratelimit:fixed:{client_id}:{window_number}
    Window number = current_time // window_seconds
    Each window gets its own key with TTL.
    """
    limit = limit or settings.default_limit
    window_seconds = window_seconds or settings.default_window_seconds

    r = await get_redis()

    # Calculate current window number and reset time
    now = int(time.time())
    window_number = now // window_seconds
    reset_at = (window_number + 1) * window_seconds
    retry_after = reset_at - now

    # Redis key for this client in this window
    key = f"ratelimit:fixed:{client_id}:{window_number}"

    # Atomic increment — creates key if not exists
    # Pipeline ensures both commands run together
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds + 1)  # +1 buffer
    results = await pipe.execute()

    current_count = results[0]
    allowed = current_count <= limit
    remaining = max(0, limit - current_count)

    return RateLimitResult(
        allowed=allowed,
        client_id=client_id,
        limit=limit,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=retry_after if not allowed else 0,
        algorithm="fixed_window",
        current_count=current_count,
    )


async def get_current_count(client_id: str, window_seconds: int = None) -> int:
    """Get current request count for a client in the current window."""
    window_seconds = window_seconds or settings.default_window_seconds
    r = await get_redis()
    now = int(time.time())
    window_number = now // window_seconds
    key = f"ratelimit:fixed:{client_id}:{window_number}"
    count = await r.get(key)
    return int(count) if count else 0