from datetime import datetime, timezone
from typing import Optional


class ReplayClock:
    """Monotonic Replay Clock for deterministic backtesting without wall-clock dependency."""

    def __init__(self, initial_time: Optional[datetime] = None) -> None:
        if initial_time is not None and initial_time.tzinfo is None:
            initial_time = initial_time.replace(tzinfo=timezone.utc)
        self._current_time: Optional[datetime] = initial_time

    def now(self) -> datetime:
        if self._current_time is None:
            raise RuntimeError("REPLAY_CLOCK_UNINITIALIZED: ReplayClock time has not been set")
        return self._current_time

    def advance_to(self, event_time: datetime) -> None:
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        if self._current_time is not None and event_time < self._current_time:
            raise ValueError(
                f"REPLAY_CLOCK_TIME_REGRESSION: Cannot regress time from {self._current_time} to {event_time}"
            )
        self._current_time = event_time
