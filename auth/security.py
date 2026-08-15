"""Central security policy for sessions, browser origins, and login throttling."""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

logger = logging.getLogger("celo_trader.auth.security")

JWT_ALGORITHM = "HS256"
COOKIE_NAME = "celo_session"
_DEV_SECRET = secrets.token_urlsafe(48)
_PRODUCTION_ORIGINS = frozenset({
    "https://celotrader.com",
    "https://www.celotrader.com",
})


def is_production() -> bool:
    return os.getenv("CELO_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower() in {
        "production", "prod",
    }


def jwt_secret() -> str:
    """Return a strong session secret; never use a checked-in fallback."""
    value = os.getenv("JWT_SECRET", "").strip()
    if len(value) >= 32:
        return value
    if is_production():
        raise RuntimeError("JWT_SECRET must be set to at least 32 characters in production")
    logger.warning("JWT_SECRET is not configured; using an ephemeral development-only secret")
    return _DEV_SECRET


def allowed_browser_origins() -> list[str]:
    origins = set(_PRODUCTION_ORIGINS)
    configured = os.getenv("CELO_ALLOWED_ORIGINS", "")
    origins.update(value.strip().rstrip("/") for value in configured.split(",") if value.strip())
    if not is_production():
        origins.update({"http://localhost:5173", "http://localhost:3000"})
    return sorted(origins)


def origin_is_trusted(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except Exception:
        return False
    return origin in set(allowed_browser_origins())


def validate_security_configuration() -> None:
    """Fail application startup when production secrets are not durable."""
    if not is_production():
        return
    jwt_secret()
    if not os.getenv("ENCRYPTION_KEY", "").strip():
        raise RuntimeError("ENCRYPTION_KEY must be set in production")


class LoginAttemptGuard:
    """Small process-local limiter that slows password guessing."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 15 * 60):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._failures[key]
            self._prune(bucket, now)
            return len(bucket) >= self.max_failures

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._failures[key]
            self._prune(bucket, now)
            bucket.append(now)

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


LOGIN_GUARD = LoginAttemptGuard()
