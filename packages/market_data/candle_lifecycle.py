from datetime import datetime
from typing import Dict, Optional, Tuple

from packages.events.envelope import DomainEventEnvelope
from packages.market_data.models import Candle


class CandleLifecycleManager:
    """Manages candle lifecycle, ensuring only closed candles trigger market.candle_closed events."""

    def __init__(self):
        # Stores last closed candle open_time for each (exchange, symbol, timeframe)
        self._last_closed_open_time: Dict[Tuple[str, str, str], datetime] = {}

    def process_candle(self, candle: Candle) -> Tuple[bool, Optional[DomainEventEnvelope]]:
        """Processes a candle object. Returns (is_new_closed_event, envelope_or_none)."""
        if not candle.is_closed:
            return False, None

        key = (candle.exchange, candle.symbol, candle.timeframe.value)
        last_time = self._last_closed_open_time.get(key)

        # Prevent duplicate closed candle emission
        if last_time and candle.open_time <= last_time:
            return False, None

        # Record closed open_time
        self._last_closed_open_time[key] = candle.open_time

        envelope = DomainEventEnvelope(
            event_type="market.candle_closed",
            aggregate_type="market_data",
            aggregate_id=f"{candle.exchange}:{candle.symbol}:{candle.timeframe.value}",
            payload=candle.model_dump(mode="json")
        )
        return True, envelope
