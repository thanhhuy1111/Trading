"""Shared FastAPI dependencies for the AI Trading Advisor routes.

`require_advisor_api_key` is a minimal, self-contained control: the rest of this API
(apps/api/routers/*) ships with NO authentication anywhere (see
docs/review/FINDINGS_REGISTER.md F-12) -- that is a pre-existing gap in the base system
this feature does not attempt to fix. This dependency only protects the NEW chat/
recommendation routes added for the advisor, per the implementation plan's explicit
"Chat và recommendation API phải có authentication nếu không chỉ chạy local" requirement.

Behaviour: if ADVISOR_API_KEY is unset AND ENVIRONMENT == "development", requests are
allowed through (local dev convenience, logged once). In any other environment, or once
a key is configured, the `X-API-Key` header must match exactly or the request is rejected
with 401.
"""

import time
from collections import deque
from typing import Deque, Dict

from fastapi import Header, HTTPException

from packages.chat_agent.config import orchestrator_settings
from packages.common.config import settings
from packages.common.logger import logger

_dev_warning_logged = False


class _SlidingWindowRateLimiter:
    """Coarse, process-global, in-memory sliding-window limiter.

    No per-user identity exists anywhere in this system (F-12: no auth at all on the base
    API), so this limits total request volume per bucket name rather than per caller. That
    is a real, if blunt, protection against runaway Gemini spend and accidental request
    storms; it is not a substitute for per-user rate limiting once real authentication
    exists.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}

    def check(self, bucket: str, limit_per_minute: int) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        hits = self._hits.setdefault(bucket, deque())
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= limit_per_minute:
            return False
        hits.append(now)
        return True


_rate_limiter = _SlidingWindowRateLimiter()


async def enforce_chat_rate_limit() -> None:
    if not _rate_limiter.check("chat", orchestrator_settings.CHAT_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="Chat rate limit exceeded, please retry shortly")


async def enforce_scan_rate_limit() -> None:
    if not _rate_limiter.check("scan", orchestrator_settings.RECOMMENDATION_SCAN_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="Recommendation scan rate limit exceeded, please retry shortly")


async def require_advisor_api_key(x_api_key: str = Header(default="")) -> None:
    global _dev_warning_logged

    if not orchestrator_settings.ADVISOR_API_KEY:
        if settings.ENVIRONMENT == "development":
            if not _dev_warning_logged:
                logger.warning(
                    "advisor_api_key_not_configured_dev_mode",
                    extra={"environment": settings.ENVIRONMENT},
                )
                _dev_warning_logged = True
            return
        raise HTTPException(status_code=503, detail="Advisor API key is not configured for this environment")

    if x_api_key != orchestrator_settings.ADVISOR_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
