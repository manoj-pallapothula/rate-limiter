import json
import redis.asyncio as aioredis
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


REDIS_KEY = "ratelimit:route_configs"


async def get_route_config(route: str) -> dict | None:
    """Get rate limit config for a specific route."""
    r = await get_redis()
    data = await r.hget(REDIS_KEY, route)
    return json.loads(data) if data else None


async def set_route_config(
    route: str,
    limit: int,
    window_seconds: int,
    algorithm: str = "sliding_window",
    by: str = "ip",
) -> dict:
    """Set rate limit config for a route."""
    r = await get_redis()
    config = {
        "route": route,
        "limit": limit,
        "window_seconds": window_seconds,
        "algorithm": algorithm,
        "by": by,
    }
    await r.hset(REDIS_KEY, route, json.dumps(config))
    return config


async def delete_route_config(route: str) -> bool:
    """Delete rate limit config for a route."""
    r = await get_redis()
    deleted = await r.hdel(REDIS_KEY, route)
    return deleted > 0


async def get_all_route_configs() -> list[dict]:
    """Get all configured routes."""
    r = await get_redis()
    data = await r.hgetall(REDIS_KEY)
    return [json.loads(v) for v in data.values()]