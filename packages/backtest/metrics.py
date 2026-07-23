import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from packages.backtest.models import BacktestMetrics, TradeEpisode


class PerformanceMetricsEngine:
    """Calculates comprehensive backtest performance metrics."""

    def _periodic_returns(self, equity_curve: List[Decimal]) -> List[float]:
        returns: List[float] = []
        for prev, cur in zip(equity_curve, equity_curve[1:]):
            if prev > Decimal("0"):
                returns.append(float((cur - prev) / prev))
        return returns

    def _risk_adjusted_ratios(
        self,
        equity_curve: List[Decimal],
        duration_days: int,
        annualized_return_pct: Optional[Decimal],
        max_dd_pct: Decimal,
    ) -> tuple:
        """Computes Sharpe, Sortino and Calmar from the realized equity curve.

        Zero risk-free rate (standard for crypto perpetual/spot research). Periods-per-year
        is inferred from the actual bar count over the wall-clock duration, so the
        annualization factor is correct regardless of the dataset timeframe (1h, 4h, 1d...).
        """
        returns = self._periodic_returns(equity_curve)
        if len(returns) < 2 or duration_days <= 0:
            return None, None, None

        periods_per_year = len(returns) / (duration_days / 365.25)

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance)

        sharpe: Optional[Decimal] = None
        if std_r > 0:
            sharpe = Decimal(str(round((mean_r / std_r) * math.sqrt(periods_per_year), 4)))

        downside_returns = [r for r in returns if r < 0]
        sortino: Optional[Decimal] = None
        if downside_returns:
            downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
            downside_std = math.sqrt(downside_variance)
            if downside_std > 0:
                sortino = Decimal(str(round((mean_r / downside_std) * math.sqrt(periods_per_year), 4)))

        calmar: Optional[Decimal] = None
        if annualized_return_pct is not None and max_dd_pct > Decimal("0"):
            calmar = Decimal(str(round(float(annualized_return_pct) / float(max_dd_pct), 4)))

        return sharpe, sortino, calmar

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

        sharpe_ratio, sortino_ratio, calmar_ratio = self._risk_adjusted_ratios(
            equity_curve, duration_days, annualized_return_pct, max_dd_pct_formatted
        )

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
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            total_fees=total_fees,
            total_slippage_cost=total_slippage,
            created_at=now
        )


metrics_engine = PerformanceMetricsEngine()
