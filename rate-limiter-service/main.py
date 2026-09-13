import logging
import os
import time
from pathlib import Path

import httpx
import redis
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rate-limiter")

app = FastAPI(title="Rate Limiter Service")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
SHORTENER_URL = os.getenv("SHORTENER_URL", "http://shortener-service:8000")

MAX_TOKENS = int(os.getenv("RATE_LIMIT_MAX_TOKENS", 10))     # bucket capacity
REFILL_RATE = float(os.getenv("RATE_LIMIT_REFILL_RATE", 1))  # tokens/sec

# ---- Fault tolerance policy ----
# FAIL_OPEN=true  -> if Redis is unreachable, let requests through (favours availability)
# FAIL_OPEN=false -> if Redis is unreachable, reject requests      (favours protection)
FAIL_OPEN = os.getenv("FAIL_OPEN", "true").lower() == "true"

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    socket_connect_timeout=0.5,  # don't hang the request waiting on a dead Redis
    socket_timeout=0.5,
    decode_responses=True,
)

LUA_SCRIPT = Path(__file__).parent.joinpath("token_bucket.lua").read_text()
token_bucket_script = redis_client.register_script(LUA_SCRIPT)

# ---- Simple circuit breaker so we don't hammer a dead Redis on every request ----
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_after_seconds: int = 10):
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self.failure_count = 0
        self.opened_at = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.reset_after_seconds:
            # cooldown elapsed -> allow one trial request through ("half-open")
            self.opened_at = None
            self.failure_count = 0
            return False
        return True

    def record_success(self):
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold and self.opened_at is None:
            self.opened_at = time.time()
            logger.warning("Circuit breaker OPEN - Redis considered unhealthy")

breaker = CircuitBreaker()


def check_rate_limit(client_id: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Encapsulates the fault-tolerance decision in one place.
    """
    if breaker.is_open():
        logger.warning("Circuit open, skipping Redis call for client=%s", client_id)
        return (FAIL_OPEN, "circuit_open")

    try:
        key = f"bucket:{client_id}"
        now = time.time()
        result = token_bucket_script(
            keys=[key],
            args=[MAX_TOKENS, REFILL_RATE, now, 1],
        )
        breaker.record_success()
        allowed = bool(int(result[0]))
        return (allowed, "ok")
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
        breaker.record_failure()
        logger.error("Redis unreachable (%s). Failing %s.", e, "OPEN" if FAIL_OPEN else "CLOSED")
        return (FAIL_OPEN, "redis_down")


@app.get("/health")
def health():
    try:
        redis_client.ping()
        redis_status = "connected"
    except redis.exceptions.RedisError:
        redis_status = "unreachable"
    return {"status": "ok", "service": "rate-limiter", "redis": redis_status, "fail_open": FAIL_OPEN}


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def gateway(path: str, request: Request):
    # In a real deployment, client_id would come from an API key or auth token.
    # For this project, we identify clients by IP address for simplicity.
    client_id = request.client.host

    allowed, reason = check_rate_limit(client_id)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded", "reason": reason},
            headers={"Retry-After": "1"},
        )

    # Forward the request to the shortener service
    body = await request.body()
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            upstream = await client.request(
                method=request.method,
                url=f"{SHORTENER_URL}/{path}",
                content=body,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        except httpx.RequestError as e:
            logger.error("Upstream shortener service unreachable: %s", e)
            return JSONResponse(status_code=502, content={"error": "Upstream service unavailable"})

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"content-type": upstream.headers.get("content-type", "application/json")},
    )