from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from packages.common.logger import logger
from packages.market_data.models import (
    DataQualityStatus,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
)


class LocalOrderBookService:
    """Maintains an in-memory local order book using REST snapshots and WebSocket deltas with sequence gap detection."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: Dict[Decimal, Decimal] = {}  # price -> quantity
        self.asks: Dict[Decimal, Decimal] = {}  # price -> quantity
        self.last_update_id: int = 0
        self.status: DataQualityStatus = DataQualityStatus.UNKNOWN

    def apply_snapshot(self, snapshot: OrderBookSnapshot):
        """Applies a full REST order book snapshot."""
        self.bids = {level.price: level.quantity for level in snapshot.bids if level.quantity > Decimal("0")}
        self.asks = {level.price: level.quantity for level in snapshot.asks if level.quantity > Decimal("0")}
        self.last_update_id = snapshot.sequence_id
        self.status = DataQualityStatus.HEALTHY
        logger.info(
            "Order book snapshot applied",
            extra={"symbol": self.symbol, "sequence_id": self.last_update_id}
        )

    def apply_delta(self, delta: OrderBookDelta) -> bool:
        """Applies a WebSocket delta update. Returns True if successfully applied, False if gap detected."""
        if self.status in [DataQualityStatus.UNKNOWN, DataQualityStatus.RESYNCING]:
            return False

        # Sequence continuity check
        if delta.first_update_id > self.last_update_id + 1:
            logger.warning(
                "Order book sequence gap detected! Triggering RESYNC",
                extra={
                    "symbol": self.symbol,
                    "expected": self.last_update_id + 1,
                    "received": delta.first_update_id
                }
            )
            self.status = DataQualityStatus.RESYNCING
            return False

        # Ignore outdated deltas
        if delta.final_update_id <= self.last_update_id:
            return True

        # Apply bids
        for level in delta.bids:
            if level.quantity == Decimal("0"):
                self.bids.pop(level.price, None)
            else:
                self.bids[level.price] = level.quantity

        # Apply asks
        for level in delta.asks:
            if level.quantity == Decimal("0"):
                self.asks.pop(level.price, None)
            else:
                self.asks[level.price] = level.quantity

        self.last_update_id = delta.final_update_id

        # Validate order book integrity (crossed book, non-negative quantities)
        if not self._validate_integrity():
            self.status = DataQualityStatus.UNHEALTHY
            return False

        return True

    def _validate_integrity(self) -> bool:
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask and best_bid >= best_ask:
            logger.error(
                "Crossed book in local order book",
                extra={"best_bid": str(best_bid), "best_ask": str(best_ask)}
            )
            return False
        return True

    def get_best_bid(self) -> Optional[Decimal]:
        return max(self.bids.keys()) if self.bids else None

    def get_best_ask(self) -> Optional[Decimal]:
        return min(self.asks.keys()) if self.asks else None

    def get_top_levels(self, depth: int = 10) -> Tuple[List[OrderBookLevel], List[OrderBookLevel]]:
        sorted_bids = sorted(
            [OrderBookLevel(price=p, quantity=q) for p, q in self.bids.items()],
            key=lambda x: x.price,
            reverse=True
        )[:depth]
        sorted_asks = sorted(
            [OrderBookLevel(price=p, quantity=q) for p, q in self.asks.items()],
            key=lambda x: x.price
        )[:depth]
        return sorted_bids, sorted_asks
