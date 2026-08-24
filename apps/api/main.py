"""Policy Search API — FastAPI application factory.

Security posture (issue #21):
- CORS is disabled unless CORS_ORIGINS is set to explicit origins. The web
  tier proxies /api/* server-side, so browsers never call this API directly.
- Standard security headers on every response; responses are no-store.
- Requests larger than MAX_REQUEST_BODY_BYTES are rejected with 413.
- POST endpoints are rate-limited per client IP (fixed window, in-process).
"""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers import health, search

_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))
_MAX_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(1024 * 1024)))

# (client_ip, window_start_epoch) -> request count. Single-instance Lightsail
# deployment; the process-local store is sufficient and never persists.
_rate_counts: dict[tuple[str, int], int] = {}


def _reset_rate_limit_state() -> None:
    """Test hook — clear the in-process rate window counters."""
    _rate_counts.clear()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


app = FastAPI(
    title="Policy Search API",
    description="Unified youth and small-business policy search API",
    version="0.0.0",
)

_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_enforcement(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)

    if request.method == "POST":
        window = int(time.monotonic()) // _RATE_WINDOW_SECONDS
        key = (_client_ip(request), window)
        _rate_counts[key] = _rate_counts.get(key, 0) + 1
        if _rate_counts[key] > _RATE_LIMIT:
            retry_after = _RATE_WINDOW_SECONDS - (int(time.monotonic()) % _RATE_WINDOW_SECONDS)
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(max(retry_after, 1))},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(health.router)
app.include_router(search.router)
