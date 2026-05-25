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
    queue_size: float


async def check(
    client_id: str,
    limit: int = None,
    window_seconds: int = None,
) -> RateLimitResult:
    """
    Leaky bucket rate limit check.

    The bucket has a fixed capacity. Requests drip out at a fixed rate.
    If the bucket is full — request is dropped.

    Stores two values in Redis:
    - queue: current number of requests in the bucket
    - last_leak: timestamp of last leak calculation

    On each request:
    1. Calculate how many requests have leaked out since last check
    2. Subtract leaked requests from queue
    3. If queue < capacity: add request, allow
    4. If queue >= capacity: drop request, block
    """
    capacity = limit or settings.default_limit
    window_seconds = window_seconds or settings.default_window_seconds

    # Leak rate: requests per second
    leak_rate = capacity / window_seconds

    r = await get_redis()
    now = time.time()

    queue_key = f"ratelimit:leaky:{client_id}:queue"
    last_leak_key = f"ratelimit:leaky:{client_id}:last_leak"

    # Get current state
    queue_val = await r.get(queue_key)
    last_leak_val = await r.get(last_leak_key)

    if queue_val is None:
        # First request — empty bucket
        queue = 0.0
        last_leak = now
    else:
        queue = float(queue_val)
        last_leak = float(last_leak_val)

        # Calculate how much has leaked since last check
        elapsed = now - last_leak
        leaked = elapsed * leak_rate
        queue = max(0.0, queue - leaked)

    # Try to add request to bucket
    if queue <= capacity - 1:
        queue += 1
        allowed = True
    else:
        allowed = False

    # Save state
    pipe = r.pipeline()
    pipe.set(queue_key, str(queue), ex=window_seconds * 2)
    pipe.set(last_leak_key, str(now), ex=window_seconds * 2)
    await pipe.execute()

    remaining = max(0, int(capacity - queue))
    retry_after = 0 if allowed else int(1 / leak_rate) + 1
    reset_at = int(now + queue / leak_rate)

    return RateLimitResult(
        allowed=allowed,
        client_id=client_id,
        limit=capacity,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=retry_after,
        algorithm="leaky_bucket",
        current_count=int(queue),
        queue_size=round(queue, 2),
    )


async def get_queue_size(client_id: str) -> float:
    """Get current queue size for a client."""
    r = await get_redis()
    queue_val = await r.get(f"ratelimit:leaky:{client_id}:queue")
    return float(queue_val) if queue_val else 0.0