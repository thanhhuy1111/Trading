import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from packages.common.logger import logger


class WebSocketConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class WebSocketIngestionCollector:
    """Manages WebSocket connection lifecycle, auto-reconnect, jittered backoff, and state transitions."""

    def __init__(
        self,
        exchange: str = "binance",
        max_reconnect_attempts: int = 5,
        base_reconnect_delay_sec: float = 1.0
    ):
        self.connection_id = f"ws_conn_{str(uuid4())[:8]}"
        self.exchange = exchange
        self.max_reconnect_attempts = max_reconnect_attempts
        self.base_reconnect_delay_sec = base_reconnect_delay_sec
        self.state = WebSocketConnectionState.DISCONNECTED
        self.reconnect_count = 0
        self.last_message_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self._running = False

    def transition_to(self, new_state: WebSocketConnectionState, reason: Optional[str] = None):
        logger.info(
            "WebSocket state transition",
            extra={
                "connection_id": self.connection_id,
                "from_state": self.state.value,
                "to_state": new_state.value,
                "reason": reason
            }
        )
        self.state = new_state
        if reason:
            self.last_error = reason

    async def connect(self, symbols: List[str]):
        """Simulates initiating a resilient WebSocket subscription connection."""
        self._running = True
        self.transition_to(WebSocketConnectionState.CONNECTING, "Initiating connection")
        await asyncio.sleep(0.1)
        self.transition_to(WebSocketConnectionState.CONNECTED, "Connected to public streams")
        self.reconnect_count = 0
        self.last_message_at = datetime.now(timezone.utc)

    async def handle_disconnect(self):
        """Triggers exponential backoff reconnect attempt."""
        if not self._running:
            return

        self.reconnect_count += 1
        if self.reconnect_count > self.max_reconnect_attempts:
            self.transition_to(WebSocketConnectionState.FAILED, "Max reconnect attempts exceeded")
            return

        self.transition_to(
            WebSocketConnectionState.RECONNECTING,
            f"Attempt {self.reconnect_count}/{self.max_reconnect_attempts}"
        )
        delay = self.base_reconnect_delay_sec * (2 ** (self.reconnect_count - 1))
        await asyncio.sleep(min(delay, 10.0))
        self.transition_to(WebSocketConnectionState.CONNECTED, "Reconnected successfully")

    async def stop(self):
        self._running = False
        self.transition_to(WebSocketConnectionState.STOPPED, "User requested shutdown")

    def get_status_info(self) -> Dict:
        return {
            "connection_id": self.connection_id,
            "exchange": self.exchange,
            "state": self.state.value,
            "reconnect_count": self.reconnect_count,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "last_error": self.last_error
        }
