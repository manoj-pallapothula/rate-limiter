import functools
from fastapi import Request, HTTPException
from app.algorithms import fixed_window, sliding_window, token_bucket, leaky_bucket
from app.config import settings


# Map algorithm names to their check functions
ALGORITHMS = {
    "fixed_window":   fixed_window.check,
    "sliding_window": sliding_window.check,
    "token_bucket":   token_bucket.check,
    "leaky_bucket":   leaky_bucket.check,
}


def get_client_id(request: Request, by: str = "header") -> str:
    """
    Extract client identifier from the request.

    by="header"  — uses X-Client-ID header (default)
    by="ip"      — uses client IP address
    by="api_key" — uses X-API-Key header
    """
    if by == "ip":
        # Handle proxies — check X-Forwarded-For first
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host

    elif by == "api_key":
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header required"
            )
        return f"apikey:{api_key}"

    else:  # header (default)
        client_id = request.headers.get("X-Client-ID", "anonymous")
        return client_id


def rate_limit(
    limit: int = None,
    window_seconds: int = None,
    algorithm: str = "sliding_window",
    by: str = "header",
):
    """
    Decorator that adds rate limiting to any FastAPI endpoint.

    Usage:
        @app.get("/api/data")
        @rate_limit(limit=100, window_seconds=60, algorithm="sliding_window")
        async def get_data(request: Request):
            return {"data": "..."}

    Args:
        limit:          Max requests allowed in the window
        window_seconds: Window size in seconds
        algorithm:      fixed_window, sliding_window, token_bucket, leaky_bucket
        by:             How to identify clients — header, ip, or api_key
    """
    _limit = limit or settings.default_limit
    _window = window_seconds or settings.default_window_seconds

    if algorithm not in ALGORITHMS:
        raise ValueError(
            f"Unknown algorithm: {algorithm}. "
            f"Choose: {', '.join(ALGORITHMS.keys())}"
        )

    check_fn = ALGORITHMS[algorithm]

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Find the Request object in args or kwargs
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

            # Get client identifier
            client_id = get_client_id(request, by=by)

            # Check rate limit
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

            # Add rate limit headers to response
            response = await func(*args, **kwargs)
            return response

        return wrapper
    return decorator