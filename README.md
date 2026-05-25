# Rate Limiter

Four rate limiting algorithms — fixed window, sliding window, token bucket, 
leaky bucket — with a React dashboard, a decorator for wrapping any FastAPI 
route, and proper IP extraction that handles proxies and load balancers.

I built this because rate limiting comes up in almost every system design 
interview and I wanted to understand the tradeoffs from actually implementing 
them, not from reading about them. The boundary burst problem in fixed window 
sounds abstract until you watch it happen live in a chart.

---

## The four algorithms

### Fixed Window

Divide time into fixed buckets. Count requests in the current bucket. 
Reset at the boundary.

Fast and simple. One problem: burst at the window boundary. Set a limit of 
10 per minute and someone can send 10 requests at 0:59 and 10 more at 1:00 
— 20 requests in 2 seconds on a "10 per minute" limit. The simulator makes 
this obvious.

Redis: INCR + EXPIRE

### Sliding Window

Counts requests in the last N seconds from right now. The window moves with you.

No boundary burst. More accurate. Uses Redis sorted sets — each request stored 
with its timestamp as the score. To check: remove old entries, add the new one, 
count what's left.

Redis: ZADD + ZREMRANGEBYSCORE + ZCARD

### Token Bucket

A bucket fills with tokens at a fixed rate. Each request costs one token. 
Empty bucket means blocked. Tokens accumulate when idle, up to capacity.

Allows controlled bursts — if you haven't made requests in a while, tokens 
pile up and you can fire a burst. What AWS API Gateway and Stripe use.

Redis: GET + SET with refill calculation on each request

### Leaky Bucket

Requests go into a bucket. They drip out at a fixed rate regardless of how 
fast they arrive. If the bucket overflows — request is dropped.

Smooths bursts completely. Unlike token bucket, the output rate is always 
fixed. Used for network traffic shaping.

Redis: GET + SET with leak rate calculation on each request

---

## Algorithm tradeoffs

| | Fixed Window | Sliding Window | Token Bucket | Leaky Bucket |
|---|---|---|---|---|
| Boundary burst | Yes | No | Controlled | No |
| Allows burst | No | No | Yes | No |
| Redis ops | 2 | 4 | 3 | 3 |
| Accuracy | Low | High | Medium | High |
| Output rate fixed | No | No | No | Yes |
| Used by | Simple APIs | Most systems | AWS, Stripe | nginx, routers |

---

## Middleware

Wrap any FastAPI route with one decorator:

```python
from app.middleware import rate_limit

@app.get("/api/data")
@rate_limit(limit=100, window_seconds=60, algorithm="sliding_window", by="ip")
async def get_data(request: Request):
    return {"data": "..."}
```

Three ways to identify clients:

```python
by="ip"      # Real IP with proxy support (X-Forwarded-For, CF-Connecting-IP)
by="header"  # X-Client-ID header
by="api_key" # X-API-Key header
```

Blocked requests get a 429 with proper headers:

X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1234567890
Retry-After: 23

---

## IP Extraction

Handles the full proxy chain in order:

CF-Connecting-IP     — Cloudflare
X-Real-IP            — nginx
X-Forwarded-For      — load balancers (takes first IP — the real client)
request.client.host  — direct connection fallback

---

## Run it

```bash
# Requires Redis
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

---

## Run it

```bash
# Requires Redis
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

POST   /check                    Check if a request is allowed
POST   /check/bulk               Check multiple clients at once
GET    /stats/clients            All clients currently being limited
GET    /stats/client/{id}        Stats for one client across all algorithms
DELETE /stats/client/{id}        Reset a client
GET    /stats/ip/{ip}            Rate limit status for an IP address
DELETE /stats/ip/{ip}            Reset all state for an IP
GET    /stats/summary            Active limiter counts per algorithm
GET    /demo/strict              5 req/min by IP — sliding window
GET    /demo/generous            100 req/min by IP — token bucket
GET    /demo/fixed               10 req/30s by header — fixed window

### Example — check request

```bash
curl -X POST http://localhost:8002/check \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "user_123",
    "algorithm": "sliding_window",
    "limit": 100,
    "window_seconds": 60
  }'
```

Allowed:
```json
{
  "allowed": true,
  "remaining": 99,
  "retry_after_seconds": 0,
  "algorithm": "sliding_window"
}
```

Blocked:
```json
{
  "allowed": false,
  "remaining": 0,
  "retry_after_seconds": 23,
  "algorithm": "sliding_window"
}
```

---

## Stack

- **Python + FastAPI** — API layer
- **Redis** — all state. Different data structures per algorithm.
- **React + Recharts** — dashboard with live charts and traffic simulator
- **pytest** — 14 tests, all mocked, no real Redis needed

---

## Project layout

app/
├── main.py                 FastAPI app, CORS, demo routes
├── config.py               .env settings
├── middleware.py           @rate_limit decorator + IP extraction
├── algorithms/
│   ├── fixed_window.py     INCR + EXPIRE
│   ├── sliding_window.py   ZADD + ZCARD + ZREMRANGEBYSCORE
│   ├── token_bucket.py     GET + SET + refill math
│   └── leaky_bucket.py     GET + SET + leak rate math
└── routers/
├── limiter.py          /check endpoints
└── stats.py            /stats + /ip endpoints
frontend/
└── src/App.js              React dashboard
tests/
├── test_fixed_window.py    5 tests
├── test_sliding_window.py  4 tests
└── test_token_bucket.py    5 tests

---

## Things that weren't obvious until I built it

**Different algorithms need different Redis primitives.** Fixed window is a 
counter — INCR is perfect. Sliding window needs to store timestamps and query 
by range — sorted sets are the only clean way. Token bucket and leaky bucket 
both use plain GET/SET but with different math. The algorithm determines the 
data structure.

**Atomic operations matter more than you'd think.** Two requests at the same 
millisecond can both read "1 remaining" and both pass through. Redis pipelines 
and atomic commands handle this without locks. GET then SET is wrong. INCR is right.

**The boundary burst problem is worse than it sounds.** I tested it in the 
simulator — 10 requests at the end of one window, 10 more at the start of the 
next, all allowed, 20 requests in under a second. Sliding window handled the 
same burst correctly. The chart made it click.

**X-Forwarded-For can have multiple IPs.** Format is 
`client, proxy1, proxy2`. The real client is always first. Taking the last 
IP or the whole string is wrong and a common mistake.

**retry_after changes client behavior.** Without it clients guess and usually 
retry immediately — which makes the problem worse. Sliding window returns the 
exact time until the oldest request falls out. Token bucket returns time to 
refill one token. Both are precise.

**leaky bucket isn't just token bucket with different math.** The output rate 
is genuinely fixed — no accumulation, no burst allowance. It's the right 
choice when you need smooth output, not just limited input.

---

## What's missing

- Distributed rate limiting — all state is in one Redis instance right now.
  Across multiple servers you need shared Redis or a consensus protocol.
- Per-route configuration storage — limits are hardcoded in the decorator.
  A database-backed config would let you change limits without redeploying.
- Rate limit by user ID from JWT — extract the subject claim from a token
  and rate limit authenticated users separately from anonymous ones.

---

## License

MIT