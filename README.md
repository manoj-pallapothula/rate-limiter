# Rate Limiter

Three rate limiting algorithms — fixed window, sliding window, token bucket — 
with a React dashboard that lets you fire bursts of traffic and watch requests 
get blocked in real time.

I built this because rate limiting comes up in almost every system design 
interview and I wanted to understand the tradeoffs from actually implementing 
them, not from reading about them. The boundary burst problem in fixed window 
sounds abstract until you watch it happen in a chart.

## The three algorithms

### Fixed Window

Divide time into buckets. Count requests in the current bucket. Reset when the 
bucket ends.

Simple. Fast. One problem: burst at the boundary. Set a limit of 10 per minute 
and someone can send 10 requests at 0:59 and 10 more at 1:00 — 20 requests 
in 2 seconds. The chart in the dashboard makes this obvious.

Redis: INCR ratelimit:fixed:{client}:{window_number}

### Sliding Window

Counts requests in the last N seconds from right now, not from a fixed start 
time. The window moves with you.

No boundary burst. More accurate. Uses Redis sorted sets — each request gets 
stored with its timestamp as the score. To check, count members in the last N 
seconds and remove the old ones.

Redis: ZADD, ZREMRANGEBYSCORE, ZCARD

### Token Bucket

A bucket fills with tokens at a fixed rate. Each request costs one token. 
Empty bucket means blocked. Tokens accumulate when you're idle, up to capacity.

Allows controlled bursts. If you haven't made requests in a while, tokens 
pile up and you can fire a burst. What AWS API Gateway uses.

Redis: GET/SET with refill calculation on each request

## Tradeoffs

| | Fixed Window | Sliding Window | Token Bucket |
|---|---|---|---|
| Boundary burst | Yes | No | Controlled |
| Redis ops per request | 2 | 4 | 3 |
| Accuracy | Low | High | Medium |
| Allows burst | No | No | Yes |
| Used by | Simple APIs | Most production systems | AWS, Stripe |


## Run it

```bash
# Requires Redis. Quickest way if you have Docker:
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

Backend docs at **http://localhost:8002/docs**
Dashboard at **http://localhost:3000**

---

## API

POST   /check                 Check if a request is allowed
POST   /check/bulk            Check multiple clients at once
GET    /stats/clients         All clients currently being limited
GET    /stats/client/{id}     Stats for one client across all algorithms
DELETE /stats/client/{id}     Reset a client — clears all Redis keys
GET    /stats/summary         Active limiter counts per algorithm

Send any algorithm per request — you don't configure it server-side:

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

Allowed response:
```json
{
  "allowed": true,
  "remaining": 99,
  "retry_after_seconds": 0,
  "algorithm": "sliding_window"
}
```

Blocked response:
```json
{
  "allowed": false,
  "remaining": 0,
  "retry_after_seconds": 23,
  "algorithm": "sliding_window"
}
```

---

## Dashboard

The traffic simulator lets you pick an algorithm, set a limit, and fire N 
requests in a burst. You see in real time which ones get through and which 
ones get blocked.

Switch between algorithms and compare — same burst, different behavior. 
The fixed window boundary burst is the most interesting one to watch.

---

## Stack

- **Python + FastAPI** — the rate limit API
- **Redis** — all state lives here. Different data structures per algorithm.
- **React + Recharts** — dashboard and traffic simulator
- **pytest** — 14 tests, all mocked, no real Redis needed

---

## Project layout


app/
├── main.py               FastAPI app, CORS config
├── config.py             .env settings
├── algorithms/
│   ├── fixed_window.py   INCR + EXPIRE
│   ├── sliding_window.py ZADD + ZCARD + ZREMRANGEBYSCORE
│   └── token_bucket.py   GET + SET + refill math
└── routers/
├── limiter.py        /check endpoints
└── stats.py          /stats endpoints
frontend/
└── src/App.js            React dashboard
tests/
├── test_fixed_window.py
├── test_sliding_window.py
└── test_token_bucket.py

## Things that weren't obvious until I built it

**Different algorithms need different Redis primitives.** Fixed window is just 
a counter — INCR is perfect. Sliding window needs to store individual 
timestamps and query by range — sorted sets are the only clean way to do that. 
Token bucket needs to store two values and do arithmetic between requests. 
The algorithm determines the data structure, not the other way around.

**Atomic operations or you get race conditions.** Two requests arriving at the 
same millisecond can both read "1 remaining" and both get through. Redis 
pipelines and atomic commands handle this without locks. GET then SET is wrong. 
INCR is right.

**The boundary burst is worse than it sounds.** I tested it with the simulator — 
10 requests at the end of one window, 10 more at the start of the next, all 
allowed, 20 requests in under a second on a "10 per minute" limit. Switching 
to sliding window in the same simulator: all 10 blocked. The chart made it 
click in a way text didn't.

**retry_after is not optional.** Without it, clients have to guess when to 
retry and usually hammer the API immediately. Sliding window returns the exact 
time until the oldest request falls out of the window. Token bucket returns 
the time to refill one token. Both are precise. Both make a real difference 
to client behavior.

## What's missing

- Distributed rate limiting — right now all state is in one Redis. Across 
  multiple servers you need shared Redis or a gossip protocol.
- Rate limit by IP — right now client_id is caller-defined. Easy to spoof.
- Leaky bucket — fourth algorithm. Smooths bursts more aggressively than 
  token bucket.
- Middleware — wrap any FastAPI route with rate limiting in one decorator.

## License

MIT