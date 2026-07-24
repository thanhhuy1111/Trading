from datetime import timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.execution.models import ExchangeOrderRequest, ExecutionMode, SimulatorOrderType
from packages.execution.validator_gate import execution_validation_gate
from packages.governance.decision_service import decision_service
from packages.market_data.guardian import data_guardian
from packages.market_data.models import Candle
from packages.paper.adapter import PaperExchangeAdapter
from packages.paper.journal import paper_event_journal
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager
from packages.positions.exit_governor import exit_risk_validator
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager
from packages.risk.governor import deterministic_risk_governor

# Maximum closed candles retained per (session, symbol) for feature warmup.
_MAX_BUFFER = 300


class PaperPipeline:
    """Real-Time Closed-Candle Paper Strategy Pipeline.

    Runs the SAME decision core as everything else (feature engine -> regime -> alpha agents
    -> critic -> consensus -> meta allocator) via ``decision_service``. It fabricates no
    signals, confidence, edge, or regime; every TradeIntent originates from the real pipeline
    and is re-validated by the deterministic Risk Governor and the execution validation gate.
    """

    def __init__(self, adapter: Optional[PaperExchangeAdapter] = None) -> None:
        self.adapter = adapter or PaperExchangeAdapter()
        self.position_managers: Dict[UUID, PositionManager] = {}
        self.exit_protectors: Dict[UUID, ExitProtector] = {}
        self.processed_candles: Dict[str, bool] = {}
        self.candle_buffers: Dict[Tuple[UUID, str], List[Candle]] = {}

    def get_position_manager(self, session_id: UUID) -> PositionManager:
        if session_id not in self.position_managers:
            sess = paper_session_manager.sessions.get(session_id)
            initial_cash = sess.initial_cash if sess else Decimal("100000.00")
            # F-03: each session owns an isolated ledger seeded from its own initial cash.
            self.position_managers[session_id] = PositionManager(
                account_id=f"PAPER_ACCT_{session_id.hex[:8]}",
                ledger=PortfolioLedger(initial_cash=initial_cash, account_id=f"PAPER_ACCT_{session_id.hex[:8]}"),
            )
        return self.position_managers[session_id]

    def get_exit_protector(self, session_id: UUID) -> ExitProtector:
        if session_id not in self.exit_protectors:
            self.exit_protectors[session_id] = ExitProtector()
        return self.exit_protectors[session_id]

    def _buffer(self, session_id: UUID, symbol: str) -> List[Candle]:
        return self.candle_buffers.setdefault((session_id, symbol), [])

    async def process_candle_close(self, session_id: UUID, candle: Candle) -> None:
        # Only closed candles drive the pipeline (open/forming candles are ignored).
        if not candle.is_closed:
            logger.info("Open candle ignored by PaperPipeline", extra={"session_id": str(session_id)})
            return

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

        # 1. Data Guardian Audit (fail closed)
        if not data_guardian.validate_ohlc(candle.open_price, candle.high_price, candle.low_price, candle.close_price):
            logger.warning("Data Guardian rejected candle", extra={"close_time": str(candle.close_time)})
            return

        # 2. Maintain the closed-candle buffer for feature warmup
        buffer = self._buffer(session_id, candle.symbol)
        buffer.append(candle)
        if len(buffer) > _MAX_BUFFER:
            del buffer[0:len(buffer) - _MAX_BUFFER]

        # 3. Protective exit monitoring for any open position
        pos = pos_mgr.positions.get(candle.symbol)
        if pos and pos.status != "CLOSED":
            intent, pos = exit_prot.evaluate_position_exit(
                pos, candle.close_price, candle.close_time, owner_position_manager=pos_mgr
            )
            if intent:
                approved_exit, app_status = exit_risk_validator.validate_exit_intent(
                    intent, candle.close_time, owner_position_manager=pos_mgr
                )
                if approved_exit and app_status == "APPROVED":
                    approved_minimum = approved_exit.minimum_exit_price or Decimal("0")
                    slippage_floor = candle.close_price * (
                        Decimal("1")
                        - approved_exit.maximum_slippage_bps / Decimal("10000")
                    )
                    minimum_fill_price = max(approved_minimum, slippage_floor)
                    if candle.close_price < minimum_fill_price:
                        pos_mgr.update_mark_price(
                            candle.symbol,
                            candle.close_price,
                            candle.close_time,
                        )
                        paper_event_journal.append_event(
                            session_id=session_id,
                            event_type="protective_exit_unresolved",
                            event_id=uuid4(),
                            source="paper_pipeline",
                            exchange_event_time=candle.close_time,
                            payload_str=(
                                f"symbol={candle.symbol};"
                                f"market={candle.close_price};"
                                f"approved_minimum={minimum_fill_price}"
                            ),
                        )
                        paper_session_manager.transition_status(
                            session_id,
                            PaperSessionStatus.HALTED,
                            reason="PROTECTIVE_EXIT_OUTSIDE_APPROVED_PRICE_ENVELOPE",
                        )
                        logger.warning(
                            "Paper protective exit blocked outside approved price envelope",
                            extra={
                                "session_id": str(session_id),
                                "symbol": candle.symbol,
                            },
                        )
                        return
                    req = ExchangeOrderRequest(
                        approved_order_id=approved_exit.approved_exit_order_id,
                        client_order_id=approved_exit.client_order_id,
                        exchange="binance",
                        symbol=candle.symbol,
                        side="SELL",
                        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
                        quantity=approved_exit.approved_quantity,
                        limit_price=minimum_fill_price,
                        maximum_entry_price=candle.close_price * Decimal("1.001"),
                        reference_price=candle.close_price,
                        remaining_approved_quantity=approved_exit.approved_quantity,
                        remaining_maximum_notional=approved_exit.approved_quantity * minimum_fill_price,
                        submitted_at=candle.close_time,
                        expires_at=candle.close_time + timedelta(minutes=15)
                    )
                    res, fills = await self.adapter.submit_order(req)
                    for fill in fills:
                        pos_mgr.process_fill(fill, candle.close_time)

        # Update mark price
        pos_mgr.update_mark_price(candle.symbol, candle.close_price, candle.close_time)

        # 4. Strategy & governance (only when flat and RUNNING). DEGRADED never opens new trades.
        if session.status != PaperSessionStatus.RUNNING:
            return
        pos = pos_mgr.positions.get(candle.symbol)
        if pos and pos.status != "CLOSED":
            return

        decision = await decision_service.decide(
            exchange="binance",
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            candles=list(buffer),
            as_of_time=candle.close_time,
            reference_price=candle.close_price,
        )

        # Journal the decision lineage (regime, config hash, allocation result, intent id)
        paper_event_journal.append_event(
            session_id=session_id,
            event_type="decision",
            event_id=uuid4(),
            source="decision_service",
            exchange_event_time=candle.close_time,
            payload_str=(
                f"regime={decision.market_regime.value};"
                f"result={decision.allocation.result.value};"
                f"intent={decision.trade_intent.intent_id if decision.trade_intent else 'NONE'};"
                f"cfg={decision.strategy_config_hash[:12]}"
            ),
        )

        intent = decision.trade_intent
        if intent is None:
            return

        # 5. Deterministic Risk Governor re-validation
        risk_snap = pos_mgr.get_risk_governor_snapshot(candle.close_time)
        risk_decision, approved = deterministic_risk_governor.evaluate_intent(
            intent=intent, snapshot=risk_snap, current_time=candle.close_time
        )
        if risk_decision.result != "APPROVED" or not approved:
            return

        # 6. Execution validation gate before any fill (F-06)
        val = execution_validation_gate.validate_order(approved, candle.close_time, ExecutionMode.SIMULATION)
        if not val.valid:
            logger.warning(
                "Paper execution blocked by validation gate",
                extra={"session_id": str(session_id), "rejections": val.rejection_codes},
            )
            return

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
            reference_price=candle.close_price,
            remaining_approved_quantity=approved.approved_quantity,
            remaining_maximum_notional=approved.approved_quantity * approved.maximum_entry_price,
            submitted_at=candle.close_time,
            expires_at=approved.expires_at
        )
        resp, fills = await self.adapter.submit_order(order_req)
        for fill in fills:
            pos_mgr.process_fill(
                fill,
                candle.close_time,
                initial_stop_price=approved.approved_stop_price,
                take_profit_price=intent.suggested_take_profit_price,
            )


paper_pipeline = PaperPipeline()
