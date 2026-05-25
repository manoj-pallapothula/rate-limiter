from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.limiter import router as limiter_router
from app.routers.stats import router as stats_router


app = FastAPI(
    title="Rate Limiter",
    description="Rate limiting service — fixed window, sliding window, token bucket",
    version="0.1.0",
)

# Allow React frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(limiter_router)
app.include_router(stats_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "Rate Limiter",
        "version": "0.1.0",
        "algorithms": ["fixed_window", "sliding_window", "token_bucket"],
        "docs": "http://localhost:8000/docs",
    }


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}