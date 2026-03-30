# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Auth — API authentication + rate limiting.

Simple, effective, no framework dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from aiohttp import web

log = logging.getLogger("halyn.auth")


class AuthMiddleware:
    """API key authentication + rate limiting."""

    def __init__(self, api_key: str = "", rate_limit: int = 60) -> None:
        self.api_key = api_key or os.environ.get("HALYN_API_KEY", "")
        self.rate_limit = rate_limit  # requests per minute
        self._requests: dict[str, list[float]] = {}  # ip -> timestamps
        self.enabled = bool(self.api_key)

        if not self.enabled:
            log.warning("auth.disabled — set HALYN_API_KEY to enable")

    def check(self, request: web.Request) -> str | None:
        """Returns error message if denied, None if allowed."""
        # Health endpoint is always public
        if request.path == "/health":
            return None

        # Auth check
        if self.enabled:
            key = (
                request.headers.get("X-API-Key", "")
                or request.headers.get("Authorization", "").removeprefix("Bearer ")
            )
            if not self._verify_key(key):
                log.warning("auth.denied ip=%s path=%s", request.remote, request.path)
                return "invalid or missing API key"

        # Rate limit check
        ip = request.remote or "unknown"
        now = time.monotonic()
        timestamps = self._requests.get(ip, [])
        # Clean old entries (older than 60s)
        timestamps = [t for t in timestamps if now - t < 60]
        if len(timestamps) >= self.rate_limit:
            log.warning("auth.rate_limited ip=%s count=%d", ip, len(timestamps))
            return "rate limit exceeded"
        timestamps.append(now)
        self._requests[ip] = timestamps

        return None

    def _verify_key(self, provided: str) -> bool:
        """Constant-time comparison to prevent timing attacks."""
        if not provided or not self.api_key:
            return False
        return hmac.compare_digest(provided.encode(), self.api_key.encode())


def create_auth_middleware(api_key: str = "", rate_limit: int = 60):
    """Create aiohttp middleware for auth."""
    auth = AuthMiddleware(api_key, rate_limit)

    @web.middleware
    async def middleware(request: web.Request, handler: Any) -> web.Response:
        error = auth.check(request)
        if error:
            return web.Response(
                text=f'{{"ok":false,"error":"{error}"}}',
                content_type="application/json",
                status=401 if "API key" in error else 429,
            )
        return await handler(request)

    return middleware

