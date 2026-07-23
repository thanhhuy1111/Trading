from decimal import Decimal
from uuid import UUID

from packages.backtest.models import TradeEpisode
from packages.execution.models import Fill


class AttributionEngine:
    """Constructs trade episodes and attributes PnL across strategy agents."""

    def build_trade_episode(
        self,
        session_id: UUID,
        position_id: UUID,
        symbol: str,
        buy_fill: Fill,
        sell_fill: Fill,
        exit_reason: str = "SIGNAL"
    ) -> TradeEpisode:

        gross_pnl = sell_fill.quote_quantity - buy_fill.quote_quantity
        total_fees = buy_fill.fee + sell_fill.fee

        # Slippage estimation
        buy_slip_per_unit = Decimal("0.0")
        if buy_fill.quantity > Decimal("0.0"):
            buy_slip_per_unit = abs(buy_fill.price - buy_fill.quote_quantity / buy_fill.quantity)
        buy_slippage = buy_slip_per_unit * buy_fill.quantity

        sell_slip_per_unit = Decimal("0.0")
        if sell_fill.quantity > Decimal("0.0"):
            sell_slip_per_unit = abs(sell_fill.price - sell_fill.quote_quantity / sell_fill.quantity)
        sell_slippage = sell_slip_per_unit * sell_fill.quantity

        slippage_cost = buy_slippage + sell_slippage

        net_pnl = gross_pnl - total_fees

        duration_sec = int((sell_fill.executed_at - buy_fill.executed_at).total_seconds())

        return TradeEpisode(
            session_id=session_id,
            position_id=position_id,
            symbol=symbol,
            opened_at=buy_fill.executed_at,
            closed_at=sell_fill.executed_at,
            entry_quantity=buy_fill.quantity,
            exit_quantity=sell_fill.quantity,
            average_entry_price=buy_fill.price,
            average_exit_price=sell_fill.price,
            gross_pnl=gross_pnl,
            fees=total_fees,
            slippage_cost=slippage_cost,
            net_pnl=net_pnl,
            maximum_favorable_excursion=Decimal("0.0"),
            maximum_adverse_excursion=Decimal("0.0"),
            holding_duration_seconds=max(0, duration_sec),
            exit_reason=exit_reason
        )


attribution_engine = AttributionEngine()
