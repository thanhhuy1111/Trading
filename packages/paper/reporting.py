from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from packages.paper.models import (
    PaperEquityPoint,
    PaperPortfolioReport,
    PaperTradeRecord,
)
from packages.positions.manager import PositionManager
from packages.positions.models import PositionStatus


class PaperPortfolioReporter:
    """Deterministic, code-only paper accounting reports.

    The reporter never calls an exchange or an LLM. Equity points are append-only by
    event time; replaying the same timestamp returns the existing point.
    """

    def __init__(self, initial_cash: Decimal) -> None:
        if initial_cash <= Decimal("0"):
            raise ValueError("PAPER_REPORT_ERROR: initial_cash must be positive")
        self.initial_cash = initial_cash
        self._equity: Dict[datetime, PaperEquityPoint] = {}
        self._reports: Dict[datetime, PaperPortfolioReport] = {}

    def capture(self, manager: PositionManager, as_of_time: datetime) -> PaperEquityPoint:
        snapshot = manager.get_portfolio_snapshot(as_of_time)
        point = PaperEquityPoint(
            as_of_time=as_of_time,
            cash_balance=snapshot.cash_balance,
            asset_market_value=snapshot.asset_market_value,
            nav=snapshot.nav,
            drawdown_pct=snapshot.drawdown_pct,
        )
        self._equity[as_of_time] = point
        return point

    def build(self, manager: PositionManager, as_of_time: datetime) -> PaperPortfolioReport:
        future_state = any(
            fill.executed_at > as_of_time for fill, _ in manager.fill_history
        ) or any(mark_time > as_of_time for mark_time in manager.last_mark_times.values())
        if future_state:
            exact = self._reports.get(as_of_time)
            if exact is not None:
                return exact
            raise ValueError(
                "PAPER_REPORT_TEMPORAL_ERROR: current state contains future events and "
                "no exact point-in-time capture is available"
            )

        self.capture(manager, as_of_time)
        snapshot = manager.get_portfolio_snapshot(as_of_time)
        trade_history: List[PaperTradeRecord] = []
        winning_exits = 0
        losing_exits = 0
        realized_pnl = Decimal("0")
        for fill, pnl in manager.fill_history:
            if fill.executed_at > as_of_time:
                continue
            pnl_value = pnl.realized_pnl if pnl is not None else None
            if pnl_value is not None:
                realized_pnl += pnl_value
                if pnl_value > Decimal("0"):
                    winning_exits += 1
                elif pnl_value < Decimal("0"):
                    losing_exits += 1
            trade_history.append(
                PaperTradeRecord(
                    fill_id=fill.fill_id,
                    client_order_id=fill.client_order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    quantity=fill.quantity,
                    fill_price=fill.price,
                    fee=fill.fee,
                    realized_pnl=pnl_value,
                    executed_at=fill.executed_at,
                )
            )
        resolved_exits = winning_exits + losing_exits
        win_rate = (
            Decimal(winning_exits) / Decimal(resolved_exits)
            if resolved_exits
            else Decimal("0")
        )
        active_positions = [
            position
            for position in manager.positions.values()
            if position.status != PositionStatus.CLOSED
        ]
        curve = [self._equity[key] for key in sorted(self._equity) if key <= as_of_time]
        max_drawdown = max((point.drawdown_pct for point in curve), default=Decimal("0"))
        report = PaperPortfolioReport(
            account_id=manager.account_id,
            initial_cash=self.initial_cash,
            cash_balance=snapshot.cash_balance,
            nav=snapshot.nav,
            total_return_pct=(snapshot.nav - self.initial_cash) / self.initial_cash,
            max_drawdown_pct=max_drawdown,
            total_fees=snapshot.total_fees,
            realized_pnl=realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            trade_count=len(trade_history),
            winning_exit_count=winning_exits,
            losing_exit_count=losing_exits,
            win_rate=win_rate,
            open_position_count=len(active_positions),
            equity_curve=curve,
            trade_history=trade_history,
            generated_at=as_of_time,
        )
        self._reports[as_of_time] = report
        return report
