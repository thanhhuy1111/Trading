from decimal import Decimal

from pydantic import BaseModel


class CostEstimate(BaseModel):
    fee_bps: Decimal = Decimal("10.0")        # 0.10% Taker fee
    spread_bps: Decimal = Decimal("2.0")       # 0.02% Bid-Ask spread
    slippage_bps: Decimal = Decimal("5.0")     # 0.05% Conservative market impact
    uncertainty_buffer_bps: Decimal = Decimal("5.0")
    total_cost_bps: Decimal


class ConservativeCostEstimator:
    """Estimates conservative trading costs (fees, spread, slippage, uncertainty buffer)."""

    def estimate_cost(self, symbol: str, is_taker: bool = True) -> CostEstimate:
        fee = Decimal("10.0") if is_taker else Decimal("5.0")
        spread = Decimal("2.0") if "BTC" in symbol else Decimal("4.0")
        slippage = Decimal("5.0")
        buffer = Decimal("5.0")

        total = fee + spread + slippage + buffer
        return CostEstimate(
            fee_bps=fee,
            spread_bps=spread,
            slippage_bps=slippage,
            uncertainty_buffer_bps=buffer,
            total_cost_bps=total
        )


cost_estimator = ConservativeCostEstimator()
