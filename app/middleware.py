import functools
from fastapi import Request, HTTPException
from app.algorithms import fixed_window, sliding_window, token_bucket, leaky_bucket
from app.config import settings


ALGORITHMS = {
    "fixed_window":   fixed_window.check,
    "sliding_window": sliding_window.check,
    "token_bucket":   token_bucket.check,
    "leaky_bucket":   leaky_bucket.check,
}


def extract_ip(request: Request) -> str:
    """
    Extract the real client IP from the request.

    Checks headers in order:
    1. X-Forwarded-For — set by load balancers and proxies
    2. X-Real-IP — set by nginx
    3. CF-Connecting-IP — set by Cloudflare
    4. request.client.host — direct connection fallback

    Always takes the first IP in X-Forwarded-For since that's
    the original client. Later IPs are proxy hops.
    """
    # Cloudflare
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    # nginx / most proxies
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Load balancers — format: "client, proxy1, proxy2"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # Direct connection
    if request.client:
        return request.client.host

    return "unknown"


def get_client_id(request: Request, by: str = "header") -> str:
    """
    Extract client identifier from the request.

    by="ip"      — real IP with proxy support
    by="header"  — X-Client-ID header
    by="api_key" — X-API-Key header
    """
    if by == "ip":
        return f"ip:{extract_ip(request)}"

    elif by == "api_key":
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header required"
            )
        return f"apikey:{api_key}"

    else:  # header (default)
        return request.headers.get("X-Client-ID", "anonymous")


def rate_limit(
    limit: int = None,
    window_seconds: int = None,
    algorithm: str = "sliding_window",
    by: str = "ip",
):
    """
    Decorator that adds rate limiting to any FastAPI endpoint.

    Usage:
        @app.get("/api/data")
        @rate_limit(limit=100, window_seconds=60, algorithm="sliding_window")
        async def get_data(request: Request):
            return {"data": "..."}

    Args:
        limit:          Max requests in window
        window_seconds: Window size in seconds
        algorithm:      fixed_window, sliding_window, token_bucket, leaky_bucket
        by:             ip, header, or api_key
    """
    _limit = limit or settings.default_limit
    _window = window_seconds or settings.default_window_seconds

    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm: {algorithm}")

    check_fn = ALGORITHMS[algorithm]

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")

            if request is None:
                raise HTTPException(
                    status_code=500,
                    detail="Rate limit middleware requires Request parameter"
                )

            client_id = get_client_id(request, by=by)
            result = await check_fn(client_id, _limit, _window)

            if not result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "client_id": client_id,
                        "algorithm": algorithm,
                        "limit": result.limit,
                        "retry_after_seconds": result.retry_after,
                        "reset_at": result.reset_at,
                    },
                    headers={
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": str(result.remaining),
                        "X-RateLimit-Reset": str(result.reset_at),
                        "Retry-After": str(result.retry_after),
                    }
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator