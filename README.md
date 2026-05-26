# Rate Limiter

Four rate limiting algorithms, a React dashboard with a live traffic simulator, 
a decorator that wraps any FastAPI route in one line, JWT-aware limits that 
treat authenticated users differently from anonymous ones, per-route config 
you can change without redeploying, and proven shared state across multiple 
server instances.

I built this to understand rate limiting from the inside. It comes up in 
almost every system design interview and I wanted to explain the tradeoffs 
from having implemented them, not from having read about them.

## The algorithms

### Fixed Window

Split time into buckets. Count requests per bucket. Reset at the boundary.

The problem: 10 requests at 0:59 and 10 more at 1:00 both pass — 20 requests 
in 2 seconds on a "10 per minute" limit. Run the simulator and watch it happen. 
It's more jarring than it sounds in text.

Redis: INCR ratelimit:fixed:{client}:{window_number}
EXPIRE to clean up automatically

### Sliding Window

Counts requests in the last N seconds from right now. No fixed boundaries, 
no burst exploit.

Each request is stored in a Redis sorted set with its timestamp as the score. 
To check: remove entries older than the window, count what's left. More 
expensive than fixed window but accurate.

Redis: ZADD + ZREMRANGEBYSCORE + ZCARD

### Token Bucket

A bucket fills with tokens at a fixed rate. Each request costs one token. 
If the bucket runs dry — blocked. If you've been idle, tokens accumulate up 
to capacity and you can burst.

This is what AWS API Gateway uses. The burst allowance is intentional — it 
handles legitimate traffic spikes without penalizing well-behaved clients.

Redis: GET tokens + GET last_refill → calculate refill → SET both

### Leaky Bucket

Requests go into a bucket. They drip out at a constant rate regardless of 
how fast they arrive. If the bucket overflows — request is dropped.

Unlike token bucket, there's no burst allowance. The output rate is always 
fixed. Used for network traffic shaping where you need smooth output, not 
just limited input.

Redis: GET queue + GET last_leak → calculate leak → SET both

## Algorithm comparison

| | Fixed | Sliding | Token Bucket | Leaky Bucket |
|---|---|---|---|---|
| Boundary burst | Yes | No | Controlled | No |
| Burst allowance | No | No | Yes | No |
| Output rate fixed | No | No | No | Yes |
| Redis ops/request | 2 | 4 | 3 | 3 |
| Accuracy | Low | High | Medium | High |
| Real-world use | Simple APIs | Most systems | AWS, Stripe | nginx, routers |

## Middleware

One decorator. No extra code in the route handler.

```python
from app.middleware import rate_limit

@app.get("/api/data")
@rate_limit(limit=100, window_seconds=60, algorithm="sliding_window", by="ip")
async def get_data(request: Request):
    return {"data": "..."}
```

Three ways to identify clients:

```python
by="ip"      # Real IP — handles X-Forwarded-For, X-Real-IP, CF-Connecting-IP
by="header"  # X-Client-ID header
by="api_key" # X-API-Key header
```

Blocked requests get a proper 429 with headers:

Retry-After: 23
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1234567890

## JWT-aware rate limiting

Different limits for anonymous vs authenticated users on the same endpoint.

```python
@app.get("/api/data")
@rate_limit_jwt(anonymous_limit=10, authenticated_limit=100)
async def get_data(request: Request):
    return {"data": "..."}
```

No JWT or invalid JWT → rate limited by IP at the anonymous limit.
Valid JWT → rate limited by user_id from the token's `sub` claim at the 
authenticated limit.

Tested: same endpoint, anonymous gets 3 requests then blocked, authenticated 
gets 20. Same IP, different token, completely different behavior.

---

## Per-route configuration

Change limits without touching code or redeploying.

```bash
# Override /api/data to 50 req/min using token bucket
curl -X POST http://localhost:8002/config/routes \
  -H "Content-Type: application/json" \
  -d '{
    "route": "/api/data",
    "limit": 50,
    "window_seconds": 60,
    "algorithm": "token_bucket",
    "by": "ip"
  }'
```

DB config takes priority over the decorator. Remove the config and the 
decorator values come back. Configs stored in a Redis hash — no separate 
database needed.

---

## Distributed rate limiting

All state lives in Redis. Multiple servers pointing at the same Redis instance 
share counts automatically — no extra code needed.

Proven with two server instances on different ports hitting the same counter:
instance-2: shared_counter=1
instance-1: shared_counter=2
instance-2: shared_counter=3
instance-1: shared_counter=4


One Redis. Two servers. One count.
GET /distributed/info   — shows which Redis this instance is connected to
GET /distributed/test   — increments a shared counter across instances


---

## IP extraction

Handles the full proxy chain correctly:
CF-Connecting-IP Cloudflare
X-Real-IP nginx
X-Forwarded-For load balancers — takes the FIRST IP (real client)
request.client.host direct connection fallback

Taking the last IP in X-Forwarded-For or the whole string is a common mistake. 
The real client is always first. Later IPs are proxy hops added along the way.

---

## Run it

```bash
# Redis (if you have Docker)
docker run -d -p 6379:6379 redis:7-alpine

# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002

# Frontend (separate terminal)
cd frontend
npm install
npm start
```

Backend docs: **http://localhost:8002/docs**
Dashboard: **http://localhost:3000**

---

## API
POST   /check                      Check if a request is allowed
POST   /check/bulk                 Check multiple clients
GET    /stats/clients              All active clients
GET    /stats/client/{id}          Stats for one client
DELETE /stats/client/{id}          Reset a client
GET    /stats/ip/{ip}              Stats for an IP across all algorithms
DELETE /stats/ip/{ip}              Reset an IP
GET    /stats/summary              Active limiter counts
POST   /config/routes              Set limit for a route
GET    /config/routes              List all route configs
DELETE /config/routes/{route}      Remove a route config
POST   /auth/token                 Generate a test JWT token
GET    /distributed/info           Redis connection info
GET    /distributed/test           Shared counter test
GET    /demo/strict                5/min by IP — sliding window
GET    /demo/generous              100/min by IP — token bucket
GET    /demo/fixed                 10/30s by header — fixed window
GET    /demo/jwt-protected         3/min anonymous, 20/min authenticated


---

## Stack

- **Python + FastAPI** — API layer
- **Redis** — all state. Different data structures per algorithm.
- **python-jose** — JWT encoding and decoding
- **React + Recharts** — dashboard with live traffic simulator
- **pytest** — 14 tests, mocked, no real Redis needed

---

## Project layout
app/
├── main.py                 FastAPI app, demo routes, JWT endpoints
├── config.py               .env settings + instance ID
├── middleware.py           @rate_limit, @rate_limit_jwt, IP extraction
├── jwt_auth.py             JWT create/decode, user_id extraction
├── route_config.py         Redis-backed per-route config storage
├── algorithms/
│   ├── fixed_window.py     INCR + EXPIRE
│   ├── sliding_window.py   ZADD + ZCARD + ZREMRANGEBYSCORE
│   ├── token_bucket.py     GET + SET + refill math
│   └── leaky_bucket.py     GET + SET + leak rate math
└── routers/
├── limiter.py          /check endpoints
├── stats.py            /stats + /ip endpoints
└── config.py           /config/routes endpoints
frontend/
└── src/App.js              React dashboard
tests/
├── test_fixed_window.py    5 tests
├── test_sliding_window.py  4 tests
└── test_token_bucket.py    5 tests


---

## Things that weren't obvious until I built it

**Different algorithms need different Redis primitives.** Fixed window is a 
counter — INCR is natural. Sliding window needs timestamps queryable by range 
— sorted sets are the only clean fit. Token and leaky bucket both use GET/SET 
but with completely different math. The algorithm determines the data structure, 
not the other way around.

**Atomic operations or you get race conditions.** Two requests at the same 
millisecond both reading "1 remaining" will both pass. Redis pipelines and 
atomic commands like INCR handle this without locks. GET then SET is wrong. 
Always.

**The boundary burst is worse than it sounds.** I watched it in the simulator — 
10 requests at the end of one window, 10 more at the start of the next, all 
allowed, 20 in 2 seconds on a "10 per minute" limit. Switching to sliding 
window in the same test: all blocked correctly. The chart made the difference 
obvious in a way text descriptions never do.

**X-Forwarded-For format is "client, proxy1, proxy2".** The real client is 
always first. I've seen implementations that take the last value or the whole 
string — both are wrong and both can be exploited to bypass IP-based limits.

**retry_after changes how clients behave.** Without it, clients guess when to 
retry and usually try immediately — which makes the problem worse. Sliding 
window returns the exact time until the oldest request exits the window. Token 
bucket returns the time to refill one token. Both are precise and both matter.

**Leaky bucket isn't just token bucket with different defaults.** The output 
rate is genuinely always fixed. No idle accumulation, no burst allowance at 
all. Right tool when you need smooth output, wrong tool when legitimate bursts 
should be allowed.

**Per-route config in Redis means zero downtime changes.** Set a new limit, 
it takes effect on the next request. No restart, no redeploy, no config file 
to push. For a rate limiter this is particularly useful — traffic incidents 
happen fast and you need to react faster.

---

## What's next

- Rate limit by JWT claims beyond sub — org_id, plan tier, role
- Prometheus metrics endpoint — request counts, block rates per algorithm
- Admin UI — manage route configs without curl
- Redis Cluster support — true horizontal scaling beyond a single Redis node

---

## License

MIT
