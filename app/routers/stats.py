from fastapi import APIRouter
from app.algorithms import fixed_window, sliding_window, token_bucket
from app.config import settings
import redis.asyncio as aioredis

router = APIRouter(prefix="/stats", tags=["Stats"])

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


@router.get("/clients")
async def get_all_clients():
    """
    Get all clients currently being rate limited.
    Returns counts per algorithm.
    """
    r = await get_redis()

    fixed_keys   = await r.keys("ratelimit:fixed:*")
    sliding_keys = await r.keys("ratelimit:sliding:*")
    token_keys   = await r.keys("ratelimit:token:*:tokens")

    # Extract unique client IDs
    def extract_clients(keys, prefix, suffix=""):
        clients = set()
        for key in keys:
            parts = key.replace(prefix, "")
            if suffix:
                parts = parts.replace(suffix, "")
            # Remove window number from fixed window keys
            client = ":".join(parts.split(":")[:-1]) if prefix == "ratelimit:fixed:" else parts
            clients.add(client)
        return list(clients)

    fixed_clients   = extract_clients(fixed_keys, "ratelimit:fixed:")
    sliding_clients = [k.replace("ratelimit:sliding:", "") for k in sliding_keys]
    token_clients   = [k.replace("ratelimit:token:", "").replace(":tokens", "")
                       for k in token_keys]

    all_clients = list(set(fixed_clients + sliding_clients + token_clients))

    return {
        "total_clients": len(all_clients),
        "by_algorithm": {
            "fixed_window":   len(fixed_clients),
            "sliding_window": len(sliding_clients),
            "token_bucket":   len(token_clients),
        },
        "clients": all_clients,
    }


@router.get("/client/{client_id}")
async def get_client_stats(client_id: str):
    """Get current rate limit status for a specific client across all algorithms."""
    fw_count = await fixed_window.get_current_count(client_id)
    sw_count = await sliding_window.get_current_count(client_id)
    tb_tokens = await token_bucket.get_current_tokens(client_id)

    return {
        "client_id": client_id,
        "fixed_window": {
            "current_count": fw_count,
            "limit": settings.default_limit,
        },
        "sliding_window": {
            "current_count": sw_count,
            "limit": settings.default_limit,
        },
        "token_bucket": {
            "tokens_remaining": tb_tokens,
            "capacity": settings.default_limit,
        },
    }


@router.delete("/client/{client_id}")
async def reset_client(client_id: str):
    """Reset all rate limit state for a client — useful for testing."""
    r = await get_redis()

    keys_to_delete = (
        await r.keys(f"ratelimit:fixed:{client_id}:*") +
        await r.keys(f"ratelimit:sliding:{client_id}") +
        await r.keys(f"ratelimit:token:{client_id}:*")
    )

    if keys_to_delete:
        await r.delete(*keys_to_delete)

    return {
        "reset": True,
        "client_id": client_id,
        "keys_deleted": len(keys_to_delete),
    }


@router.get("/summary")
async def get_summary():
    """High level summary — total keys in Redis per algorithm."""
    r = await get_redis()

    fixed_keys   = await r.keys("ratelimit:fixed:*")
    sliding_keys = await r.keys("ratelimit:sliding:*")
    token_keys   = await r.keys("ratelimit:token:*:tokens")

    return {
        "active_fixed_windows":    len(fixed_keys),
        "active_sliding_windows":  len(sliding_keys),
        "active_token_buckets":    len(token_keys),
        "total_active":            len(fixed_keys) + len(sliding_keys) + len(token_keys),
        "default_limit":           settings.default_limit,
        "default_window_seconds":  settings.default_window_seconds,
    }