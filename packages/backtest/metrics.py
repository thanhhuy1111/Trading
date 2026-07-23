from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from packages.backtest.models import BacktestMetrics, TradeEpisode


class PerformanceMetricsEngine:
    """Calculates comprehensive backtest performance metrics."""

    def compute_metrics(
        self,
        session_id: UUID,
        initial_nav: Decimal,
        final_nav: Decimal,
        episodes: List[TradeEpisode],
        equity_curve: List[Decimal],
        start_time: datetime,
        end_time: datetime
    ) -> BacktestMetrics:

        net_profit = final_nav - initial_nav
        if initial_nav > Decimal("0"):
            total_return_pct = (net_profit / initial_nav) * Decimal("100.0")
        else:
            total_return_pct = Decimal("0.0")

        # Duration in days for annualization
        duration_days = max(1, (end_time - start_time).days)
        annualized_return_pct: Optional[Decimal] = None
        if duration_days >= 30 and initial_nav > Decimal("0") and final_nav > Decimal("0"):
            ann_factor = Decimal("365.0") / Decimal(str(duration_days))
            ann_ret = (float(final_nav / initial_nav) ** float(ann_factor)) - 1.0
            annualized_return_pct = Decimal(str(round(ann_ret * 100.0, 4)))

        # Drawdown calculation
        max_dd_pct = Decimal("0.0")
        peak = initial_nav
        for nav in equity_curve:
            if nav > peak:
                peak = nav
            if peak > Decimal("0"):
                dd = (peak - nav) / peak
                if dd > max_dd_pct:
                    max_dd_pct = dd

        max_dd_pct_formatted = max_dd_pct * Decimal("100.0")

        total_trades = len(episodes)
        winning_trades = [e for e in episodes if e.net_pnl > Decimal("0.0")]
        losing_trades = [e for e in episodes if e.net_pnl < Decimal("0.0")]

        if total_trades > 0:
            win_rate = (Decimal(len(winning_trades)) / Decimal(total_trades)) * Decimal("100.0")
        else:
            win_rate = Decimal("0.0")

        total_gross_win = sum((e.net_pnl for e in winning_trades), Decimal("0.0"))
        total_gross_loss = abs(sum((e.net_pnl for e in losing_trades), Decimal("0.0")))

        profit_factor: Optional[Decimal] = None
        if total_gross_loss > Decimal("0"):
            profit_factor = total_gross_win / total_gross_loss

        total_fees = sum((e.fees for e in episodes), Decimal("0.0"))
        total_slippage = sum((e.slippage_cost for e in episodes), Decimal("0.0"))

        now = datetime.now(timezone.utc)

        return BacktestMetrics(
            session_id=session_id,
            initial_nav=initial_nav,
            final_nav=final_nav,
            net_profit=net_profit,
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return_pct,
            max_drawdown_pct=max_dd_pct_formatted,
            sharpe_ratio=None,
            sortino_ratio=None,
            calmar_ratio=None,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            total_fees=total_fees,
            total_slippage_cost=total_slippage,
            created_at=now
        )


metrics_engine = PerformanceMetricsEngine()
