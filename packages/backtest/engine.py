import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from packages.backtest.clock import ReplayClock
from packages.backtest.datasets import dataset_registry
from packages.backtest.metrics import metrics_engine
from packages.backtest.models import (
    BacktestConfig,
    BacktestReport,
    BacktestSession,
    BacktestStatus,
    TradeEpisode,
)
from packages.backtest.reproducibility import reproducibility_verifier
from packages.candidates.builder import build_proposed_candidate
from packages.candidates.models import CandidateStatus, TradeCandidate
from packages.common.logger import logger
from packages.execution.models import Fill, LiquidityType
from packages.governance.decision_service import decision_service
from packages.market_data.guardian import data_guardian
from packages.positions.exit_governor import exit_risk_validator
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager
from packages.risk.governor import deterministic_risk_governor

# Every registered feature calculator's required_lookback is bounded (<=28 candles for the
# "standard_v1" feature set: adx_14 needs period*2=28, the rest need <=23). This window is a
# generous multiple of that so decision quality is byte-identical to passing full history, while
# keeping per-bar feature computation O(window) instead of O(bars_processed_so_far). Without this
# bound, a multi-year replay is O(n^2) in candle count, which is the dominant cost at large-scale
# multi-symbol/multi-config research campaign runs.
FEATURE_LOOKBACK_WINDOW = 250


class EventDrivenBacktestEngine:
    """Event-Driven Backtest Engine replaying historical market data through the production-safe pipeline."""

    def __init__(self) -> None:
        self.active_sessions: Dict[UUID, BacktestSession] = {}
        self.session_configs: Dict[UUID, BacktestConfig] = {}
        self.session_candidates: Dict[UUID, List[TradeCandidate]] = {}

    def get_candidates(self, session_id: UUID) -> List[TradeCandidate]:
        """Full TradeCandidate lineage for a completed session — every proposed trade,
        whether risk-rejected, approved-but-unfilled, or filled and (if closed) its outcome."""
        return self.session_candidates.get(session_id, [])

    def create_session(self, config: BacktestConfig) -> BacktestSession:
        dataset = dataset_registry.get_dataset(config.dataset_id)
        if not dataset:
            raise ValueError(f"DATASET_NOT_FOUND: Dataset {config.dataset_id} is not registered")

        dataset_cs = dataset.checksum
        config_cs = reproducibility_verifier.compute_fingerprint(dataset_cs, config)

        now = datetime.now(timezone.utc)
        session = BacktestSession(
            name=config.session_name,
            mode=config.mode,
            status=BacktestStatus.CREATED,
            dataset_id=config.dataset_id,
            dataset_checksum=dataset_cs,
            config_checksum=config_cs,
            start_time=config.start_time,
            end_time=config.end_time,
            warmup_start_time=config.warmup_start_time,
            initial_cash=config.initial_cash,
            random_seed=config.random_seed,
            created_at=now
        )

        self.active_sessions[session.session_id] = session
        self.session_configs[session.session_id] = config
        return session

    def run_backtest(self, session_id: UUID) -> BacktestReport:
        """Synchronous entrypoint. Runs the whole session inside a single asyncio event
        loop (see `_run_backtest_async`) instead of opening/tearing down a new loop on every
        candle, which is the historical behaviour this replaces performance-wise only —
        the decision sequence and every intermediate value are unchanged."""
        return asyncio.run(self._run_backtest_async(session_id))

    async def _run_backtest_async(self, session_id: UUID) -> BacktestReport:
        session = self.active_sessions.get(session_id)
        config = self.session_configs.get(session_id)
        if not session or not config:
            raise ValueError(f"SESSION_NOT_FOUND: Session {session_id} not found")

        candles = dataset_registry.get_dataset_candles(session.dataset_id)
        if not candles:
            session.status = BacktestStatus.INVALID_DATA
            raise ValueError("CANNOT_RUN_BACKTEST: Dataset contains no candles")

        session.status = BacktestStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)

        # Isolated Session State. A dedicated PortfolioLedger seeded from config.initial_cash
        # is required here — PositionManager falls back to the module-global `portfolio_ledger`
        # singleton when no ledger is injected, which would leak cash/asset balances across
        # every backtest session sharing this process (e.g. sequential runs, or many sessions
        # sharing one worker in a parallel research campaign). Paper trading already injects
        # its own per-session ledger (packages/paper/pipeline.py); the backtest engine must too.
        clock = ReplayClock(config.warmup_start_time)
        session_account_id = f"BACKTEST_{session.session_id}"
        session_ledger = PortfolioLedger(initial_cash=config.initial_cash, account_id=session_account_id)
        pos_mgr = PositionManager(account_id=session_account_id, ledger=session_ledger)
        exit_prot = ExitProtector()

        episodes: List[TradeEpisode] = []
        equity_curve: List[Decimal] = []
        candidates: List[TradeCandidate] = []
        # At most one open position per symbol (maximum_positions=1), so a single pending
        # slot is sufficient to link a later exit fill back to the candidate that opened it.
        pending_candidate: Optional[TradeCandidate] = None

        # Filter candles for warmup and active backtest range
        all_candles = sorted(candles, key=lambda c: c.close_time)

        active_symbol = config.symbols[0] if config.symbols else "BTC/USDT"
        events_processed = 0

        # Processing loop
        for idx, candle in enumerate(all_candles):
            if candle.close_time > config.end_time:
                break

            clock.advance_to(candle.close_time)
            events_processed += 1
            session.replay_time = candle.close_time

            # 1. Data Guardian Audit
            if not data_guardian.validate_ohlc(
                candle.open_price, candle.high_price, candle.low_price, candle.close_price
            ):
                logger.warning("Data Guardian rejected candle", extra={"timestamp": str(candle.close_time)})
                continue

            # Warmup filter: do not trade during warmup window
            if candle.close_time < config.start_time:
                continue

            # 2. Check Exit Protection for existing position
            pos = pos_mgr.positions.get(active_symbol)
            if pos and pos.status != "CLOSED":
                intent, pos = exit_prot.evaluate_position_exit(
                    pos, candle.close_price, candle.close_time, owner_position_manager=pos_mgr
                )
                if intent:
                    approved_exit, app_status = exit_risk_validator.validate_exit_intent(
                        intent, candle.close_time, owner_position_manager=pos_mgr
                    )
                    if approved_exit and app_status == "APPROVED":
                        # Simulated Exit Order Execution
                        exit_price = candle.close_price * Decimal("0.999") # 10 bps slippage
                        quote_qty = approved_exit.approved_quantity * exit_price
                        fee = quote_qty * Decimal("0.001") # 10 bps fee

                        sell_fill = Fill(
                            exchange_fill_id=f"FILL_EXIT_{uuid4().hex[:8]}",
                            exchange_order_id=approved_exit.approved_exit_order_id,
                            client_order_id=approved_exit.client_order_id,
                            symbol=active_symbol,
                            side="SELL",
                            quantity=approved_exit.approved_quantity,
                            price=exit_price,
                            quote_quantity=quote_qty,
                            fee=fee,
                            fee_asset="USDT",
                            liquidity=LiquidityType.TAKER,
                            executed_at=candle.close_time
                        )

                        pos_mgr.process_fill(sell_fill, candle.close_time)

                        entry_notional = approved_exit.approved_quantity * pos.average_entry_price
                        gross_pnl = quote_qty - entry_notional
                        net_pnl = quote_qty - fee - entry_notional

                        # Record Trade Episode
                        episodes.append(
                            TradeEpisode(
                                session_id=session.session_id,
                                position_id=pos.position_id,
                                symbol=active_symbol,
                                opened_at=pos.opened_at,
                                closed_at=candle.close_time,
                                entry_quantity=approved_exit.approved_quantity,
                                exit_quantity=approved_exit.approved_quantity,
                                average_entry_price=pos.average_entry_price,
                                average_exit_price=exit_price,
                                gross_pnl=gross_pnl,
                                fees=fee,
                                slippage_cost=Decimal("0.0"),
                                net_pnl=net_pnl,
                                exit_reason=intent.trigger_type
                            )
                        )

                        # Finalize the candidate lineage entry that opened this position, if any
                        # (a position can predate candidate tracking only at the very first bar
                        # of a resumed/checkpointed session, which this engine does not support).
                        if pending_candidate is not None and entry_notional > Decimal("0"):
                            pending_candidate.status = CandidateStatus.CLOSED
                            pending_candidate.exit_timestamp = candle.close_time
                            pending_candidate.exit_price = exit_price
                            pending_candidate.gross_return_bps = (gross_pnl / entry_notional) * Decimal("10000")
                            pending_candidate.total_cost_bps = (fee / entry_notional) * Decimal("10000")
                            pending_candidate.net_return_bps = (net_pnl / entry_notional) * Decimal("10000")
                            pending_candidate.exit_reason = intent.trigger_type.value if hasattr(
                                intent.trigger_type, "value"
                            ) else str(intent.trigger_type)
                            pending_candidate.label_end_timestamp = candle.close_time
                            pending_candidate.meta_label = "ACCEPT" if net_pnl > Decimal("0") else "REJECT"
                            candidates.append(pending_candidate)
                            pending_candidate = None

            # Update mark price & NAV
            pos_mgr.update_mark_price(active_symbol, candle.close_price, candle.close_time)
            snap = pos_mgr.get_portfolio_snapshot(candle.close_time)
            equity_curve.append(snap.nav)

            # 3. Strategy & governance — SAME DecisionService as paper trading (no fabrication).
            if not pos or pos.status == "CLOSED":
                # Bounded trailing window: identical feature values to passing full history
                # (see FEATURE_LOOKBACK_WINDOW), O(window) per bar instead of O(idx).
                window_start = max(0, idx + 1 - FEATURE_LOOKBACK_WINDOW)
                buffer = all_candles[window_start:idx + 1]  # closed candles with close_time <= current bar
                decision = await decision_service.decide(
                    exchange="binance",
                    symbol=active_symbol,
                    timeframe=candle.timeframe,
                    candles=buffer,
                    as_of_time=candle.close_time,
                    reference_price=candle.close_price,
                    strategy_config=config.strategy_config,
                )
                intent = decision.trade_intent
                if intent is not None:
                    candidate = build_proposed_candidate(
                        decision=decision,
                        session_id=session.session_id,
                        strategy_name=config.session_name,
                        strategy_version=config.strategy_config.version,
                        fold_number=config.fold_number,
                    )

                    # Risk Governor Evaluation
                    risk_snap = pos_mgr.get_risk_governor_snapshot(candle.close_time)
                    risk_decision, approved = deterministic_risk_governor.evaluate_intent(
                        intent=intent,
                        snapshot=risk_snap,
                        current_time=candle.close_time
                    )

                    if candidate is not None and not (risk_decision.result == "APPROVED" and approved):
                        candidate.status = CandidateStatus.RISK_REJECTED
                        candidate.risk_rejection_reasons = list(risk_decision.rejection_codes)
                        candidates.append(candidate)
                        candidate = None
                    elif candidate is not None:
                        candidate.status = CandidateStatus.APPROVED

                    # BUY execution at NEXT event open (NO_SAME_BAR_FILL by default)
                    if (
                        risk_decision.result == "APPROVED"
                        and approved
                        and config.liquidity_config.same_bar_fill_allowed is False
                        and idx + 1 < len(all_candles)
                    ):
                        next_candle = all_candles[idx + 1]
                        # slippage vs next open, capped at the risk-approved maximum entry price
                        raw_fill = next_candle.open_price * Decimal("1.0005")
                        fill_price = min(raw_fill, approved.maximum_entry_price)
                        fill_qty = approved.approved_quantity
                        quote_qty = fill_qty * fill_price
                        fee = quote_qty * Decimal("0.001")  # 10 bps fee

                        buy_fill = Fill(
                            exchange_fill_id=f"FILL_BUY_{uuid4().hex[:8]}",
                            exchange_order_id=approved.approved_order_id,
                            client_order_id=approved.client_order_id,
                            symbol=active_symbol,
                            side="BUY",
                            quantity=fill_qty,
                            price=fill_price,
                            quote_quantity=quote_qty,
                            fee=fee,
                            fee_asset="USDT",
                            liquidity=LiquidityType.TAKER,
                            executed_at=next_candle.close_time
                        )

                        pos_mgr.process_fill(buy_fill, next_candle.close_time)

                        if candidate is not None:
                            candidate.status = CandidateStatus.FILLED
                            candidate.actual_entry_price = fill_price
                            pending_candidate = candidate
                            candidate = None

                    # Approved but never filled (e.g. no next candle) is a terminal, non-pending
                    # outcome — record it so it isn't silently dropped from the lineage.
                    if candidate is not None:
                        candidates.append(candidate)

        # An open position at dataset end has no exit yet: keep it in the ledger as FILLED
        # with no outcome fields (censored, not fabricated) rather than dropping it.
        if pending_candidate is not None:
            candidates.append(pending_candidate)

        self.session_candidates[session.session_id] = candidates

        # Compute Final Backtest Metrics
        final_nav = equity_curve[-1] if equity_curve else config.initial_cash
        session.final_nav = final_nav
        session.events_processed = events_processed
        session.status = BacktestStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)

        metrics = metrics_engine.compute_metrics(
            session_id=session.session_id,
            initial_nav=config.initial_cash,
            final_nav=final_nav,
            episodes=episodes,
            equity_curve=equity_curve,
            start_time=config.start_time,
            end_time=config.end_time
        )

        dataset = dataset_registry.get_dataset(session.dataset_id)
        dataset_name = dataset.name if dataset else "UNKNOWN"

        report = BacktestReport(
            session_id=session.session_id,
            reproducibility_fingerprint=session.config_checksum,
            metrics=metrics,
            dataset_name=dataset_name,
            dataset_checksum=session.dataset_checksum,
            trade_count=len(episodes),
            created_at=datetime.now(timezone.utc)
        )

        return report


backtest_engine = EventDrivenBacktestEngine()
