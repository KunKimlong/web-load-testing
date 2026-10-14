"""Authentication, CSRF protection, API rate limiting and security headers."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .config import Settings

CSRF_HEADER = "x-loadlab-client"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuthError(Exception):
    pass


def resolve_owner(request: Request, settings: Settings) -> str:
    """Return the principal for this request; raises AuthError if authentication fails."""
    if settings.auth_mode == "none":
        return "local"
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Missing bearer token.")
    # LOADLAB_AUTH_TOKEN may hold several comma-separated tokens; each one is a separate principal.
    valid = False
    for expected in (t.strip() for t in (settings.auth_token or "").split(",")):
        if expected and hmac.compare_digest(token.encode(), expected.encode()):
            valid = True
    if not valid:
        raise AuthError("Invalid API token.")
    return "tok_" + hashlib.sha256(token.encode()).hexdigest()[:16]


def error_body(code: str, message: str, details: object | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    def __init__(self, rate_per_s: float, burst: int, max_keys: int = 10_000):
        self.rate = rate_per_s
        self.burst = burst
        self.max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= self.max_keys:
                self._buckets.clear()  # bounded memory; worst case resets limits
            b = self._buckets[key] = _Bucket(tokens=float(self.burst), updated=now)
        b.tokens = min(self.burst, b.tokens + (now - b.updated) * self.rate)
        b.updated = now
        if b.tokens >= cost:
            b.tokens -= cost
            return True
        return False


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.limiter = TokenBucketLimiter(settings.api_rate_limit_per_s, settings.api_rate_limit_burst)
        self.start_limiter = TokenBucketLimiter(
            settings.test_start_limit_per_min / 60.0, settings.test_start_limit_per_min
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        path = request.url.path

        if path.startswith("/api/") and request.method != "OPTIONS":
            client = request.client.host if request.client else "unknown"
            if not self.limiter.allow(client):
                return self._reject(429, "rate_limited", "Too many API requests; slow down.", request_id)
            if request.method == "POST" and path == "/api/tests" and not self.start_limiter.allow(client):
                return self._reject(429, "rate_limited", "Too many test starts; wait a minute.", request_id)

            if request.method in UNSAFE_METHODS:
                origin = request.headers.get("origin")
                if origin and origin not in self.settings.cors_origins:
                    return self._reject(
                        403, "csrf_origin", "Cross-origin request from an unapproved origin.", request_id
                    )
                if request.headers.get(CSRF_HEADER) != "1":
                    return self._reject(
                        403,
                        "csrf_header",
                        f"Missing {CSRF_HEADER} header on state-changing request.",
                        request_id,
                    )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @staticmethod
    def _reject(status: int, code: str, message: str, request_id: str) -> JSONResponse:
        return JSONResponse(
            error_body(code, message), status_code=status, headers={"X-Request-ID": request_id}
        )
