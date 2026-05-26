import functools
from fastapi import Request, HTTPException
from app.algorithms import fixed_window, sliding_window, token_bucket, leaky_bucket
from app.config import settings
from app.route_config import get_route_config
from app.jwt_auth import get_user_id_from_token


ALGORITHMS = {
    "fixed_window":   fixed_window.check,
    "sliding_window": sliding_window.check,
    "token_bucket":   token_bucket.check,
    "leaky_bucket":   leaky_bucket.check,
}


def extract_ip(request: Request) -> str:
    """Extract real client IP handling proxies."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def get_client_id(request: Request, by: str = "ip") -> str:
    """Extract client identifier from request."""
    if by == "ip":
        return f"ip:{extract_ip(request)}"
    elif by == "api_key":
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        return f"apikey:{api_key}"
    else:
        return request.headers.get("X-Client-ID", "anonymous")


def get_client_id_with_jwt(request: Request, by: str = "ip") -> tuple[str, str]:
    """
    Extract client ID considering JWT authentication.
    Returns (client_id, auth_type) tuple.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user_id = get_user_id_from_token(token)
        if user_id:
            return f"user:{user_id}", "jwt"
    return get_client_id(request, by=by), by


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

            # Check DB config — overrides decorator values
            route_path = request.url.path
            db_config = await get_route_config(route_path)
            if db_config:
                _limit_actual = db_config["limit"]
                _window_actual = db_config["window_seconds"]
                _algo_actual = db_config["algorithm"]
                _by_actual = db_config["by"]
                check_fn_actual = ALGORITHMS.get(_algo_actual, check_fn)
            else:
                _limit_actual = _limit
                _window_actual = _window
                _algo_actual = algorithm
                _by_actual = by
                check_fn_actual = check_fn

            client_id = get_client_id(request, by=_by_actual)
            result = await check_fn_actual(client_id, _limit_actual, _window_actual)

            if not result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "client_id": client_id,
                        "algorithm": _algo_actual,
                        "limit": result.limit,
                        "retry_after_seconds": result.retry_after,
                        "reset_at": result.reset_at,
                        "config_source": "database" if db_config else "decorator",
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


def rate_limit_jwt(
    anonymous_limit: int = 10,
    authenticated_limit: int = 100,
    window_seconds: int = 60,
    algorithm: str = "sliding_window",
    by: str = "ip",
):
    """
    JWT-aware rate limiter.
    Anonymous users get anonymous_limit.
    Authenticated users (valid JWT) get authenticated_limit.
    """
    check_fn = ALGORITHMS.get(algorithm)
    if not check_fn:
        raise ValueError(f"Unknown algorithm: {algorithm}")

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

            client_id, auth_type = get_client_id_with_jwt(request, by=by)

            if auth_type == "jwt":
                _limit = authenticated_limit
                limit_type = "authenticated"
            else:
                _limit = anonymous_limit
                limit_type = "anonymous"

            result = await check_fn(client_id, _limit, window_seconds)

            if not result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "client_id": client_id,
                        "limit_type": limit_type,
                        "limit": result.limit,
                        "retry_after_seconds": result.retry_after,
                        "reset_at": result.reset_at,
                    },
                    headers={
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": str(result.remaining),
                        "Retry-After": str(result.retry_after),
                    }
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator