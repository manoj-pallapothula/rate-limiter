from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers.limiter import router as limiter_router
from app.routers.stats import router as stats_router
from app.middleware import rate_limit
from app.routers.config import router as config_router

app = FastAPI(
    title="Rate Limiter",
    description="Rate limiting service — fixed window, sliding window, token bucket, leaky bucket",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(limiter_router)
app.include_router(stats_router)
app.include_router(config_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "Rate Limiter",
        "version": "0.1.0",
        "algorithms": [
            "fixed_window",
            "sliding_window",
            "token_bucket",
            "leaky_bucket"
        ],
        "docs": "http://localhost:8002/docs",
    }


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}


# ── Demo routes showing middleware in action ──────────────────────────────────

@app.get("/demo/strict", tags=["Demo"])
@rate_limit(limit=5, window_seconds=60, algorithm="sliding_window", by="ip")
async def demo_strict(request: Request):
    """Strict limit — 5 requests per minute by IP."""
    return {
        "message": "You got through the strict rate limiter",
        "limit": "5 per minute",
        "algorithm": "sliding_window",
        "identified_by": "ip",
    }


@app.get("/demo/generous", tags=["Demo"])
@rate_limit(limit=100, window_seconds=60, algorithm="token_bucket", by="ip")
async def demo_generous(request: Request):
    """Generous limit — 100 requests per minute, allows bursts."""
    return {
        "message": "You got through the generous rate limiter",
        "limit": "100 per minute",
        "algorithm": "token_bucket",
        "identified_by": "ip",
    }


@app.get("/demo/fixed", tags=["Demo"])
@rate_limit(limit=10, window_seconds=30, algorithm="fixed_window", by="header")
async def demo_fixed(request: Request):
    """Fixed window — 10 requests per 30 seconds by X-Client-ID header."""
    return {
        "message": "You got through the fixed window rate limiter",
        "limit": "10 per 30 seconds",
        "algorithm": "fixed_window",
        "identified_by": "X-Client-ID header",
    }

@app.get("/distributed/info", tags=["Distributed"])
async def distributed_info():
    """
    Shows which Redis instance this server is connected to.
    In a distributed setup all servers should point to the same Redis.
    """
    import redis.asyncio as aioredis
    from app.config import settings

    r = await aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        info = await r.info("server")
        ping = await r.ping()
        return {
            "instance_id": settings.instance_id,
            "redis_url": settings.redis_url,
            "redis_connected": ping,
            "redis_version": info.get("redis_version"),
            "redis_uptime_seconds": info.get("uptime_in_seconds"),
            "note": "All instances must share the same redis_url for distributed rate limiting to work"
        }
    except Exception as e:
        return {
            "instance_id": settings.instance_id,
            "redis_url": settings.redis_url,
            "redis_connected": False,
            "error": str(e),
        }


@app.get("/distributed/test", tags=["Distributed"])
async def distributed_test():
    """
    Test distributed rate limiting.
    Hit this endpoint from multiple server instances to prove shared state.
    """
    import redis.asyncio as aioredis
    from app.config import settings

    r = await aioredis.from_url(settings.redis_url, decode_responses=True)

    key = "distributed:test:counter"
    count = await r.incr(key)
    await r.expire(key, 60)

    return {
        "instance_id": settings.instance_id,
        "shared_counter": count,
        "message": f"This request was handled by {settings.instance_id}. "
                   f"Counter is shared across all instances.",
    }