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
    tokens_remaining: float


async def check(
    client_id: str,
    limit: int = None,
    window_seconds: int = None,
) -> RateLimitResult:
    """
    Token bucket rate limit check.

    Stores two values in Redis:
    - tokens: current number of tokens in the bucket
    - last_refill: timestamp of last refill

    On each request:
    1. Calculate how many tokens to add since last refill
    2. Add tokens (up to capacity)
    3. If tokens >= 1: consume one token, allow
    4. If tokens < 1: block
    """
    capacity = limit or settings.default_limit
    window_seconds = window_seconds or settings.default_window_seconds

    # Refill rate: tokens per second
    refill_rate = capacity / window_seconds

    r = await get_redis()
    now = time.time()

    tokens_key = f"ratelimit:token:{client_id}:tokens"
    last_refill_key = f"ratelimit:token:{client_id}:last_refill"

    # Get current state
    tokens_val = await r.get(tokens_key)
    last_refill_val = await r.get(last_refill_key)

    if tokens_val is None:
        # First request — start with full bucket
        tokens = float(capacity)
        last_refill = now
    else:
        tokens = float(tokens_val)
        last_refill = float(last_refill_val)

        # Calculate tokens to add since last refill
        elapsed = now - last_refill
        tokens_to_add = elapsed * refill_rate
        tokens = min(capacity, tokens + tokens_to_add)

    # Try to consume one token
    if tokens >= 1:
        tokens -= 1
        allowed = True
    else:
        allowed = False

    # Save state back to Redis
    pipe = r.pipeline()
    pipe.set(tokens_key, str(tokens), ex=window_seconds * 2)
    pipe.set(last_refill_key, str(now), ex=window_seconds * 2)
    await pipe.execute()

    remaining = int(tokens)
    tokens_consumed = capacity - int(tokens) if allowed else capacity
    retry_after = 0 if allowed else int((1 - tokens) / refill_rate) + 1
    reset_at = int(now + (capacity - tokens) / refill_rate)

    return RateLimitResult(
        allowed=allowed,
        client_id=client_id,
        limit=capacity,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=retry_after,
        algorithm="token_bucket",
        current_count=tokens_consumed,
        tokens_remaining=round(tokens, 2),
    )


async def get_current_tokens(client_id: str) -> float:
    """Get current token count for a client."""
    r = await get_redis()
    tokens_val = await r.get(f"ratelimit:token:{client_id}:tokens")
    return float(tokens_val) if tokens_val else 0.0