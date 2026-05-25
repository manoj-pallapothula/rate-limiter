from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.route_config import (
    get_route_config, set_route_config,
    delete_route_config, get_all_route_configs
)

router = APIRouter(prefix="/config", tags=["Config"])


class RouteConfigRequest(BaseModel):
    route: str
    limit: int
    window_seconds: int
    algorithm: str = "sliding_window"
    by: str = "ip"


@router.post("/routes")
async def create_route_config(request: RouteConfigRequest):
    """Set rate limit config for a route."""
    config = await set_route_config(
        route=request.route,
        limit=request.limit,
        window_seconds=request.window_seconds,
        algorithm=request.algorithm,
        by=request.by,
    )
    return {"created": True, "config": config}


@router.get("/routes")
async def list_route_configs():
    """List all configured routes."""
    configs = await get_all_route_configs()
    return {"total": len(configs), "configs": configs}


@router.get("/routes/{route:path}")
async def get_route(route: str):
    """Get config for a specific route."""
    config = await get_route_config(route)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No config found for route: {route}"
        )
    return config


@router.delete("/routes/{route:path}")
async def delete_route(route: str):
    """Delete config for a specific route."""
    deleted = await delete_route_config(route)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No config found for route: {route}"
        )
    return {"deleted": True, "route": route}