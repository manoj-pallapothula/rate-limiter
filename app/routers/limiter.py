from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.algorithms import fixed_window, sliding_window, token_bucket, leaky_bucket

router = APIRouter(prefix="/check", tags=["Rate Limiter"])


class RateLimitRequest(BaseModel):
    client_id: str
    algorithm: str = "sliding_window"
    limit: Optional[int] = None
    window_seconds: Optional[int] = None


class RateLimitResponse(BaseModel):
    allowed: bool
    client_id: str
    algorithm: str
    limit: int
    remaining: int
    reset_at: int
    retry_after_seconds: int
    current_count: int


@router.post("", response_model=RateLimitResponse)
async def check_rate_limit(request: RateLimitRequest):
    try:
        if request.algorithm == "fixed_window":
            result = await fixed_window.check(
                request.client_id, request.limit, request.window_seconds)
        elif request.algorithm == "sliding_window":
            result = await sliding_window.check(
                request.client_id, request.limit, request.window_seconds)
        elif request.algorithm == "token_bucket":
            result = await token_bucket.check(
                request.client_id, request.limit, request.window_seconds)
        elif request.algorithm == "leaky_bucket":
            result = await leaky_bucket.check(
                request.client_id, request.limit, request.window_seconds)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown algorithm: {request.algorithm}. "
                       f"Choose: fixed_window, sliding_window, token_bucket, leaky_bucket"
            )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))

    return RateLimitResponse(
        allowed=result.allowed,
        client_id=result.client_id,
        algorithm=result.algorithm,
        limit=result.limit,
        remaining=result.remaining,
        reset_at=result.reset_at,
        retry_after_seconds=result.retry_after,
        current_count=result.current_count,
    )


@router.post("/bulk")
async def bulk_check(requests: list[RateLimitRequest]):
    results = []
    for req in requests:
        try:
            result = await check_rate_limit(req)
            results.append(result)
        except HTTPException as e:
            results.append({"error": e.detail, "client_id": req.client_id})
    return {"results": results, "total": len(results)}