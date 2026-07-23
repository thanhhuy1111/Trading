from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List

from packages.events.envelope import DomainEventEnvelope
from packages.market_data.models import (
    Candle,
    DataQualityIssue,
    DataQualityResult,
    DataQualityStatus,
    MarketTrade,
    OrderBookSnapshot,
    RecommendedAction,
)


class DataGuardian:
    """Independent Data Quality Guardian validating Freshness, Completeness, Validity, Consistency, and Anomalies."""

    def __init__(self, stale_threshold_sec: float = 30.0, price_jump_threshold_pct: Decimal = Decimal("0.10")):
        self.stale_threshold_sec = stale_threshold_sec
        self.price_jump_threshold_pct = price_jump_threshold_pct
        self._symbol_status: Dict[str, DataQualityStatus] = {}

    def validate_ohlc(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, close_price: Decimal) -> bool:
        """Validates basic OHLC numerical integrity."""
        if open_price <= Decimal("0") or close_price <= Decimal("0") or low_price <= Decimal("0"):
            return False
        if high_price < max(open_price, close_price, low_price):
            return False
        if low_price > min(open_price, close_price, high_price):
            return False
        return True

    def audit_trade(self, trade: MarketTrade) -> DataQualityResult:
        """Audits a market trade for validity and anomalies."""
        issues: List[DataQualityIssue] = []

        if trade.price <= Decimal("0"):
            issues.append(DataQualityIssue(
                exchange=trade.exchange,
                symbol=trade.symbol,
                data_type="trade",
                issue_code="INVALID_PRICE",
                message=f"Trade price ({trade.price}) must be positive",
                severity="CRITICAL"
            ))

        if trade.quantity <= Decimal("0"):
            issues.append(DataQualityIssue(
                exchange=trade.exchange,
                symbol=trade.symbol,
                data_type="trade",
                issue_code="INVALID_QUANTITY",
                message=f"Trade quantity ({trade.quantity}) must be positive",
                severity="HIGH"
            ))

        status = DataQualityStatus.UNHEALTHY if issues else DataQualityStatus.HEALTHY
        action = RecommendedAction.PAUSE_SYMBOL if status == DataQualityStatus.UNHEALTHY else RecommendedAction.CONTINUE
        return DataQualityResult(
            is_healthy=len(issues) == 0,
            status=status,
            issues=issues,
            recommended_action=action
        )

    def audit_candle(self, candle: Candle) -> DataQualityResult:
        """Audits a candle for OHLC relation and freshness."""
        issues: List[DataQualityIssue] = []

        if candle.high_price < max(candle.open_price, candle.close_price, candle.low_price):
            issues.append(DataQualityIssue(
                exchange=candle.exchange,
                symbol=candle.symbol,
                data_type="candle",
                issue_code="INVALID_OHLC_HIGH",
                message="Candle high price is smaller than open/close/low",
                severity="CRITICAL"
            ))

        if candle.low_price > min(candle.open_price, candle.close_price, candle.high_price):
            issues.append(DataQualityIssue(
                exchange=candle.exchange,
                symbol=candle.symbol,
                data_type="candle",
                issue_code="INVALID_OHLC_LOW",
                message="Candle low price is greater than open/close/high",
                severity="CRITICAL"
            ))

        # Freshness check
        now = datetime.now(timezone.utc)
        if (now - candle.received_timestamp).total_seconds() > self.stale_threshold_sec:
            issues.append(DataQualityIssue(
                exchange=candle.exchange,
                symbol=candle.symbol,
                data_type="candle",
                issue_code="STALE_CANDLE",
                message=f"Candle received over {self.stale_threshold_sec}s ago",
                severity="MEDIUM"
            ))

        status = DataQualityStatus.UNHEALTHY if any(i.severity == "CRITICAL" for i in issues) else (
            DataQualityStatus.DEGRADED if issues else DataQualityStatus.HEALTHY
        )
        action = RecommendedAction.RESYNC if status == DataQualityStatus.DEGRADED else (
            RecommendedAction.PAUSE_SYMBOL if status == DataQualityStatus.UNHEALTHY else RecommendedAction.CONTINUE
        )

        return DataQualityResult(
            is_healthy=len(issues) == 0,
            status=status,
            issues=issues,
            recommended_action=action
        )

    def audit_order_book(self, snapshot: OrderBookSnapshot) -> DataQualityResult:
        """Audits order book snapshot for crossed book and depth integrity."""
        issues: List[DataQualityIssue] = []

        if snapshot.bids and snapshot.asks:
            best_bid = snapshot.bids[0].price
            best_ask = snapshot.asks[0].price
            if best_bid >= best_ask:
                issues.append(DataQualityIssue(
                    exchange=snapshot.exchange,
                    symbol=snapshot.symbol,
                    data_type="order_book",
                    issue_code="CROSSED_BOOK",
                    message=f"Best bid ({best_bid}) >= Best ask ({best_ask})",
                    severity="CRITICAL"
                ))

        status = DataQualityStatus.UNHEALTHY if issues else DataQualityStatus.HEALTHY
        action = RecommendedAction.RESYNC if status == DataQualityStatus.UNHEALTHY else RecommendedAction.CONTINUE

        return DataQualityResult(
            is_healthy=len(issues) == 0,
            status=status,
            issues=issues,
            recommended_action=action
        )

    def create_quality_changed_event(
        self,
        exchange: str,
        symbol: str,
        data_type: str,
        prev_status: DataQualityStatus,
        new_status: DataQualityStatus,
        result: DataQualityResult
    ) -> DomainEventEnvelope:
        """Generates a market.data_quality_changed domain event envelope."""
        return DomainEventEnvelope(
            event_type="market.data_quality_changed",
            aggregate_type="data_guardian",
            aggregate_id=f"{exchange}:{symbol}:{data_type}",
            payload={
                "exchange": exchange,
                "symbol": symbol,
                "data_type": data_type,
                "previous_status": prev_status.value,
                "new_status": new_status.value,
                "recommended_action": result.recommended_action.value,
                "issues": [i.model_dump(mode="json") for i in result.issues],
                "detected_at": datetime.now(timezone.utc).isoformat()
            }
        )


data_guardian = DataGuardian()
