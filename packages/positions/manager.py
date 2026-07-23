from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from packages.execution.models import Fill
from packages.positions.ledger import PortfolioLedger, portfolio_ledger
from packages.positions.models import (
    LedgerEntry,
    PortfolioSnapshot,
    Position,
    PositionStatus,
    RealizedPnlEntry,
    ValuationQuality,
)
from packages.risk.models import PortfolioRiskSnapshot, PositionRiskView


class PositionManager:
    """Position Manager tracking open positions, cost basis, valuation, and snapshots."""

    def __init__(self, account_id: str = "SIM_ACCOUNT_001", ledger: Optional[PortfolioLedger] = None) -> None:
        self.account_id = account_id
        # F-03: a session may inject its own ledger for full isolation. When none is given we
        # fall back to the module-global ledger (legacy / default behaviour, unchanged).
        if ledger is None:
            self.ledger = portfolio_ledger
            self.equity_peak = Decimal("100000.00")
        else:
            self.ledger = ledger
            self.equity_peak = ledger.cash_balance
        self.positions: Dict[str, Position] = {}
        # F-05: realized PnL is tracked in time-bucketed windows (UTC day / ISO week),
        # never as a lifetime-cumulative counter.
        self.realized_pnl_buckets: Dict[Tuple[str, str], Decimal] = {}
        self.realized_fee_buckets: Dict[Tuple[str, str], Decimal] = {}
        # Real fill history for this account (most recent last), for dashboards/audit — every
        # fill that has actually been applied via apply_fill_accounting, paired with the
        # RealizedPnlEntry produced (None for BUY fills / position-opening fills).
        self.fill_history: List[Tuple[Fill, Optional[RealizedPnlEntry]]] = []

    @staticmethod
    def _utc_day_key(dt: datetime) -> str:
        d = dt.astimezone(timezone.utc)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()

    @staticmethod
    def _iso_week_key(dt: datetime) -> str:
        d = dt.astimezone(timezone.utc)
        monday = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=d.weekday())
        return monday.isoformat()

    def _record_realized_pnl(self, pnl: Decimal, fee: Decimal, event_time: datetime) -> None:
        dkey = ("DAILY", self._utc_day_key(event_time))
        wkey = ("WEEKLY", self._iso_week_key(event_time))
        self.realized_pnl_buckets[dkey] = self.realized_pnl_buckets.get(dkey, Decimal("0.0")) + pnl
        self.realized_pnl_buckets[wkey] = self.realized_pnl_buckets.get(wkey, Decimal("0.0")) + pnl
        self.realized_fee_buckets[dkey] = self.realized_fee_buckets.get(dkey, Decimal("0.0")) + fee
        self.realized_fee_buckets[wkey] = self.realized_fee_buckets.get(wkey, Decimal("0.0")) + fee

    def realized_pnl_window(self, bucket_type: str, at_time: datetime) -> Decimal:
        if bucket_type == "DAILY":
            key = ("DAILY", self._utc_day_key(at_time))
        else:
            key = ("WEEKLY", self._iso_week_key(at_time))
        return self.realized_pnl_buckets.get(key, Decimal("0.0"))

    def process_fill(
        self,
        fill: Fill,
        current_time: Optional[datetime] = None
    ) -> Tuple[Position, Optional[RealizedPnlEntry]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        pos = self.positions.get(fill.symbol)
        avg_entry = pos.average_entry_price if pos else Decimal("0.0")

        # 1. Update Portfolio Ledger (session-scoped)
        entries, pnl_entry = self.ledger.process_fill(fill, current_time, avg_entry)

        return self.apply_fill_accounting(fill, entries, pnl_entry)

    def apply_fill_accounting(
        self,
        fill: Fill,
        entries: List[LedgerEntry],  # noqa: ARG002 (accepted for API symmetry with process_fill)
        pnl_entry: Optional[RealizedPnlEntry],
    ) -> Tuple[Position, Optional[RealizedPnlEntry]]:
        """Applies position/PnL-bucket bookkeeping for a fill whose ledger entries were already
        computed elsewhere (e.g. by the durable fill-commit orchestrator, which persists the same
        `entries`/`pnl_entry` to PostgreSQL before calling this). Kept separate from
        ``process_fill`` so the durable path never re-invokes (and re-dedupes against) the ledger."""
        if pnl_entry:
            # F-05: bucket realized PnL by the fill's event time (UTC day / ISO week)
            self._record_realized_pnl(pnl_entry.realized_pnl, pnl_entry.exit_fee, fill.executed_at)

        self.fill_history.append((fill, pnl_entry))

        pos = self.positions.get(fill.symbol)

        if fill.side == "BUY":
            if not pos or pos.status == PositionStatus.CLOSED:
                # Open New Position
                cost_basis = fill.quote_quantity + fill.fee
                avg_price = cost_basis / fill.quantity
                pos = Position(
                    account_id=self.account_id,
                    exchange="binance",
                    symbol=fill.symbol,
                    side="LONG",
                    status=PositionStatus.OPEN,
                    quantity=fill.quantity,
                    available_quantity=fill.quantity,
                    reserved_exit_quantity=Decimal("0.0"),
                    average_entry_price=avg_price,
                    total_cost_basis=cost_basis,
                    realized_pnl=Decimal("0.0"),
                    unrealized_pnl=Decimal("0.0"),
                    total_fees=fill.fee,
                    current_market_price=fill.price,
                    market_value=fill.quantity * fill.price,
                    opened_at=fill.executed_at,
                    last_fill_at=fill.executed_at,
                    version=1
                )
            else:
                # Increase Existing Position
                new_qty = pos.quantity + fill.quantity
                new_cost = pos.total_cost_basis + fill.quote_quantity + fill.fee
                new_avg = new_cost / new_qty
                pos = pos.model_copy(update={
                    "quantity": new_qty,
                    "available_quantity": pos.available_quantity + fill.quantity,
                    "average_entry_price": new_avg,
                    "total_cost_basis": new_cost,
                    "total_fees": pos.total_fees + fill.fee,
                    "last_fill_at": fill.executed_at,
                    "version": pos.version + 1
                })

        elif fill.side == "SELL":
            if not pos or pos.quantity < fill.quantity:
                raise ValueError("INSUFFICIENT_POSITION_QUANTITY: Cannot SELL more than open LONG position quantity")

            new_qty = pos.quantity - fill.quantity
            released_cost = fill.quantity * pos.average_entry_price
            
            # Full close threshold tolerance check
            is_full_close = new_qty <= Decimal("1e-8")
            if is_full_close:
                new_qty = Decimal("0.0")
                new_avail_qty = Decimal("0.0")
                new_reserved_qty = Decimal("0.0")
                new_cost = Decimal("0.0")
                unrealized = Decimal("0.0")
                status = PositionStatus.CLOSED
            else:
                new_avail_qty = max(Decimal("0.0"), pos.available_quantity - fill.quantity)
                new_reserved_qty = pos.reserved_exit_quantity
                new_cost = max(Decimal("0.0"), pos.total_cost_basis - released_cost)
                unrealized = pos.unrealized_pnl
                status = PositionStatus.PARTIALLY_CLOSED

            pos = pos.model_copy(update={
                "quantity": new_qty,
                "available_quantity": new_avail_qty,
                "reserved_exit_quantity": new_reserved_qty,
                "total_cost_basis": new_cost,
                "unrealized_pnl": unrealized,
                "realized_pnl": pos.realized_pnl + (pnl_entry.realized_pnl if pnl_entry else Decimal("0.0")),
                "total_fees": pos.total_fees + fill.fee,
                "status": status,
                "closed_at": fill.executed_at if status == PositionStatus.CLOSED else None,
                "last_fill_at": fill.executed_at,
                "version": pos.version + 1
            })

        self.positions[fill.symbol] = pos
        return pos, pnl_entry

    def update_mark_price(
        self,
        symbol: str,
        mark_price: Decimal,
        current_time: Optional[datetime] = None
    ) -> Optional[Position]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        pos = self.positions.get(symbol)
        if not pos or pos.status == PositionStatus.CLOSED:
            return None

        mkt_val = pos.quantity * mark_price
        unrealized = mkt_val - pos.total_cost_basis
        pos = pos.model_copy(update={
            "current_market_price": mark_price,
            "market_value": mkt_val,
            "unrealized_pnl": unrealized,
            "version": pos.version + 1
        })
        self.positions[symbol] = pos
        return pos

    def get_portfolio_snapshot(self, current_time: Optional[datetime] = None) -> PortfolioSnapshot:
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        active_positions = [p for p in self.positions.values() if p.status != PositionStatus.CLOSED]
        asset_mkt_val = sum((p.market_value for p in active_positions if p.market_value), Decimal("0.0"))
        nav = self.ledger.cash_balance + asset_mkt_val

        if nav > self.equity_peak:
            self.equity_peak = nav

        drawdown = Decimal("0.0")
        if self.equity_peak > Decimal("0"):
            drawdown = max(Decimal("0.0"), (self.equity_peak - nav) / self.equity_peak)

        risk_views = []
        for p in active_positions:
            m_price = p.current_market_price or p.average_entry_price
            s_price = p.active_stop_price or Decimal("0.0")
            risk_amt = max(Decimal("0.0"), m_price - s_price) * p.quantity
            risk_views.append(
                PositionRiskView(
                    symbol=p.symbol,
                    side="LONG",
                    quantity=p.quantity,
                    average_entry_price=p.average_entry_price,
                    current_price=m_price,
                    market_value=p.market_value or (p.quantity * m_price),
                    unrealized_pnl=p.unrealized_pnl,
                    stop_price=p.active_stop_price or p.initial_stop_price,
                    open_risk_amount=risk_amt
                )
            )

        return PortfolioSnapshot(
            account_id=self.account_id,
            cash_balance=self.ledger.cash_balance,
            available_cash=self.ledger.available_cash,
            asset_market_value=asset_mkt_val,
            nav=nav,
            gross_exposure=asset_mkt_val,
            net_exposure=asset_mkt_val,
            open_risk_amount=Decimal("0.0"),
            realized_pnl_today=self.realized_pnl_window("DAILY", current_time),
            realized_pnl_week=self.realized_pnl_window("WEEKLY", current_time),
            unrealized_pnl=sum((p.unrealized_pnl for p in active_positions), Decimal("0.0")),
            total_fees=sum((p.total_fees for p in self.positions.values()), Decimal("0.0")),
            equity_peak=self.equity_peak,
            drawdown_pct=drawdown,
            positions=risk_views,
            valuation_quality=ValuationQuality.HEALTHY,
            data_as_of=current_time,
            generated_at=current_time
        )

    def get_risk_governor_snapshot(self, current_time: Optional[datetime] = None) -> PortfolioRiskSnapshot:
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        snap = self.get_portfolio_snapshot(current_time)
        return PortfolioRiskSnapshot(
            account_id=self.account_id,
            nav=snap.nav,
            cash_balance=snap.cash_balance,
            available_cash=snap.available_cash,
            gross_exposure=snap.gross_exposure,
            net_exposure=snap.net_exposure,
            open_risk_amount=sum((p.open_risk_amount for p in snap.positions), Decimal("0.0")),
            realized_pnl_today=snap.realized_pnl_today,
            realized_pnl_week=snap.realized_pnl_week,
            unrealized_pnl=snap.unrealized_pnl,
            equity_peak=snap.equity_peak,
            current_drawdown_pct=snap.drawdown_pct,
            positions=snap.positions,
            pending_orders=[],
            data_as_of=current_time,
            snapshot_source="POSITION_MANAGER",
            is_stale=False
        )


position_manager = PositionManager(ledger=portfolio_ledger)
