"""Rate limiting for the AI Trading Advisor `/chat` route.

Authentication/authorization for this route is `apps.api.deps.require_permission` (the same
RBAC every other recommendation-architecture endpoint uses) -- this module only adds a coarse
spend/abuse guard on top, since RBAC alone does not bound how often an authorized principal
can trigger a paid Gemini API call.
"""

import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException

from packages.chat_agent.config import gemini_settings, orchestrator_settings


class _SlidingWindowRateLimiter:
    """Coarse, process-global, in-memory sliding-window limiter per bucket name."""

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


async def enforce_analysis_rate_limit() -> None:
    """Bound paid multi-LLM analysis calls independently from conversational chat."""
    if (
        not gemini_settings.is_configured
        or not gemini_settings.GEMINI_CONTEXT_ENABLED
    ):
        return
    if not _rate_limiter.check(
        "analysis",
        orchestrator_settings.ANALYSIS_RATE_LIMIT_PER_MINUTE,
    ):
        raise HTTPException(
            status_code=429,
            detail="Analysis rate limit exceeded, please retry shortly",
        )
