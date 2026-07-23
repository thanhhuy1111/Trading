from datetime import timedelta
from decimal import Decimal
from typing import Dict, Optional
from uuid import UUID, uuid4

from packages.agents.models import MarketRegime
from packages.common.logger import logger
from packages.execution.models import ExchangeOrderRequest, SimulatorOrderType
from packages.governance.models import IntentSide, TradeIntent
from packages.market_data.guardian import data_guardian
from packages.market_data.models import Candle
from packages.paper.adapter import PaperExchangeAdapter
from packages.paper.journal import paper_event_journal
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager
from packages.positions.exit_governor import exit_risk_validator
from packages.positions.exit_protector import ExitProtector
from packages.positions.manager import PositionManager
from packages.risk.governor import deterministic_risk_governor


class PaperPipeline:
    """Real-Time Closed-Candle Paper Strategy Pipeline."""

    def __init__(self, adapter: Optional[PaperExchangeAdapter] = None) -> None:
        self.adapter = adapter or PaperExchangeAdapter()
        self.position_managers: Dict[UUID, PositionManager] = {}
        self.exit_protectors: Dict[UUID, ExitProtector] = {}
        self.processed_candles: Dict[str, bool] = {}

    def get_position_manager(self, session_id: UUID) -> PositionManager:
        if session_id not in self.position_managers:
            self.position_managers[session_id] = PositionManager(account_id=f"PAPER_ACCT_{session_id.hex[:8]}")
        return self.position_managers[session_id]

    def get_exit_protector(self, session_id: UUID) -> ExitProtector:
        if session_id not in self.exit_protectors:
            self.exit_protectors[session_id] = ExitProtector()
        return self.exit_protectors[session_id]

    async def process_candle_close(self, session_id: UUID, candle: Candle) -> None:
        session = paper_session_manager.sessions.get(session_id)
        if not session or session.status not in [PaperSessionStatus.RUNNING, PaperSessionStatus.DEGRADED]:
            logger.warning("Paper pipeline skipped: session inactive", extra={"session_id": str(session_id)})
            return

        # Deduplication check
        tf_str = candle.timeframe.value if hasattr(candle.timeframe, "value") else candle.timeframe
        dedup_key = f"{session_id}:{candle.symbol}:{tf_str}:{candle.close_time.isoformat()}"
        if dedup_key in self.processed_candles:
            logger.info("Duplicate candle skipped by PaperPipeline", extra={"dedup_key": dedup_key})
            return

        self.processed_candles[dedup_key] = True

        # Journal market event
        paper_event_journal.append_event(
            session_id=session_id,
            event_type="candle_close",
            event_id=uuid4(),
            source="public_stream",
            exchange_event_time=candle.close_time,
            payload_str=dedup_key
        )

        pos_mgr = self.get_position_manager(session_id)
        exit_prot = self.get_exit_protector(session_id)

        # 1. Data Guardian Audit
        if not data_guardian.validate_ohlc(candle.open_price, candle.high_price, candle.low_price, candle.close_price):
            logger.warning(
                "Data Guardian rejected candle in paper pipeline",
                extra={"close_time": str(candle.close_time)}
            )
            return

        # 2. Protective Exit Monitoring
        pos = pos_mgr.positions.get(candle.symbol)
        if pos and pos.status != "CLOSED":
            intent, pos = exit_prot.evaluate_position_exit(pos, candle.close_price, candle.close_time)
            if intent:
                approved_exit, app_status = exit_risk_validator.validate_exit_intent(intent, candle.close_time)
                if approved_exit and app_status == "APPROVED":
                    req = ExchangeOrderRequest(
                        approved_order_id=approved_exit.approved_exit_order_id,
                        client_order_id=approved_exit.client_order_id,
                        exchange="binance",
                        symbol=candle.symbol,
                        side="SELL",
                        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
                        quantity=approved_exit.approved_quantity,
                        limit_price=candle.close_price * Decimal("0.999"),
                        maximum_entry_price=candle.close_price * Decimal("1.001"),
                        remaining_approved_quantity=approved_exit.approved_quantity,
                        remaining_maximum_notional=approved_exit.approved_quantity * candle.close_price,
                        submitted_at=candle.close_time,
                        expires_at=candle.close_time + timedelta(minutes=15)
                    )
                    res, fills = await self.adapter.submit_order(req)
                    for fill in fills:
                        pos_mgr.process_fill(fill, candle.close_time)

        # Update mark price
        pos_mgr.update_mark_price(candle.symbol, candle.close_price, candle.close_time)

        # 3. Strategy & Governance Signal Processing (Only if no open position and RUNNING)
        if session.status == PaperSessionStatus.RUNNING and (not pos or pos.status == "CLOSED"):
            # Strategy TradeIntent
            intent = TradeIntent(
                intent_id=uuid4(),
                symbol=candle.symbol,
                exchange="binance",
                side=IntentSide.BUY,
                strategy_ids=["PAPER_TREND_V1"],
                source_signal_ids=[uuid4()],
                critic_decision_ids=[uuid4()],
                consensus_id=uuid4(),
                market_regime=MarketRegime.TREND_UP,
                expected_return_bps=Decimal("150.0"),
                weighted_confidence=Decimal("0.85"),
                estimated_fee_bps=Decimal("10.0"),
                estimated_spread_bps=Decimal("5.0"),
                estimated_slippage_bps=Decimal("5.0"),
                uncertainty_buffer_bps=Decimal("10.0"),
                net_edge_bps=Decimal("120.0"),
                reference_price=candle.close_price,
                suggested_stop_price=candle.close_price * Decimal("0.98"),
                suggested_take_profit_price=candle.close_price * Decimal("1.05"),
                horizon_minutes=60,
                feature_as_of_time=candle.close_time,
                generated_at=candle.close_time,
                expires_at=candle.close_time + timedelta(minutes=15)
            )

            # Revalidate with Deterministic Risk Governor
            risk_snap = pos_mgr.get_risk_governor_snapshot(candle.close_time)
            decision, approved = deterministic_risk_governor.evaluate_intent(
                intent=intent,
                snapshot=risk_snap,
                current_time=candle.close_time
            )

            if decision.result == "APPROVED" and approved:
                order_req = ExchangeOrderRequest(
                    approved_order_id=approved.approved_order_id,
                    client_order_id=approved.client_order_id,
                    exchange="binance",
                    symbol=candle.symbol,
                    side="BUY",
                    order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
                    quantity=approved.approved_quantity,
                    limit_price=approved.maximum_entry_price,
                    maximum_entry_price=approved.maximum_entry_price,
                    remaining_approved_quantity=approved.approved_quantity,
                    remaining_maximum_notional=approved.approved_quantity * approved.maximum_entry_price,
                    submitted_at=candle.close_time,
                    expires_at=approved.expires_at
                )

                resp, fills = await self.adapter.submit_order(order_req)
                for fill in fills:
                    pos_mgr.process_fill(fill, candle.close_time)


paper_pipeline = PaperPipeline()
