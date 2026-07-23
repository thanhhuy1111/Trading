from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List
from uuid import UUID, uuid4

from packages.agents.models import MarketRegime
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
from packages.common.logger import logger
from packages.execution.models import Fill, LiquidityType
from packages.governance.models import IntentSide, TradeIntent
from packages.market_data.guardian import data_guardian
from packages.positions.exit_governor import exit_risk_validator
from packages.positions.exit_protector import ExitProtector
from packages.positions.manager import PositionManager
from packages.risk.governor import deterministic_risk_governor


class EventDrivenBacktestEngine:
    """Event-Driven Backtest Engine replaying historical market data through the production-safe pipeline."""

    def __init__(self) -> None:
        self.active_sessions: Dict[UUID, BacktestSession] = {}
        self.session_configs: Dict[UUID, BacktestConfig] = {}

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

        # Isolated Session State
        clock = ReplayClock(config.warmup_start_time)
        session_account_id = f"BACKTEST_{session.session_id}"
        pos_mgr = PositionManager(account_id=session_account_id)
        exit_prot = ExitProtector()

        episodes: List[TradeEpisode] = []
        equity_curve: List[Decimal] = []

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
                intent, pos = exit_prot.evaluate_position_exit(pos, candle.close_price, candle.close_time)
                if intent:
                    approved_exit, app_status = exit_risk_validator.validate_exit_intent(intent, candle.close_time)
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
                                gross_pnl=quote_qty - (approved_exit.approved_quantity * pos.average_entry_price),
                                fees=fee,
                                slippage_cost=Decimal("0.0"),
                                net_pnl=quote_qty - fee - (approved_exit.approved_quantity * pos.average_entry_price),
                                exit_reason=intent.trigger_type
                            )
                        )

            # Update mark price & NAV
            pos_mgr.update_mark_price(active_symbol, candle.close_price, candle.close_time)
            snap = pos_mgr.get_portfolio_snapshot(candle.close_time)
            equity_curve.append(snap.nav)

            # 3. Strategy Signals (only if no open position and NO_SAME_BAR_FILL)
            if not pos or pos.status == "CLOSED":
                # Simulated Trend Strategy Signal Generator
                if idx >= 5:
                    prev_close = all_candles[idx - 5].close_price
                    if candle.close_price > prev_close * Decimal("1.01"): # 1% uptrend rule
                        # Generate TradeIntent
                        intent = TradeIntent(
                            intent_id=uuid4(),
                            symbol=active_symbol,
                            exchange="binance",
                            side=IntentSide.BUY,
                            strategy_ids=["TREND_FOLLOWING_V1"],
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

                        # Risk Governor Evaluation
                        risk_snap = pos_mgr.get_risk_governor_snapshot(candle.close_time)
                        decision, approved = deterministic_risk_governor.evaluate_intent(
                            intent=intent,
                            snapshot=risk_snap,
                            current_time=candle.close_time
                        )

                        if decision.result == "APPROVED" and approved:

                            # Simulated BUY execution at NEXT event (NO_SAME_BAR_FILL)
                            if config.liquidity_config.same_bar_fill_allowed is False and idx + 1 < len(all_candles):
                                next_candle = all_candles[idx + 1]
                                fill_price = next_candle.open_price * Decimal("1.0005") # 5 bps slippage
                                fill_qty = approved.approved_quantity
                                quote_qty = fill_qty * fill_price
                                fee = quote_qty * Decimal("0.001") # 10 bps fee

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
