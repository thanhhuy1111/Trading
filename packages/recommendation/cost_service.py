"""Cost facts for the recommendation domain -- reuses the real governance cost estimator.

Never re-implements fee/spread/slippage assumptions locally; wraps
packages.governance.cost_estimator so the recommendation layer and the executed paper /
backtest pipelines always agree on what a trade costs.
"""

from decimal import Decimal

from pydantic import BaseModel

from packages.governance.cost_estimator import cost_estimator


class CostBreakdown(BaseModel):
    fee_bps: Decimal
    spread_bps: Decimal
    slippage_bps: Decimal
    uncertainty_buffer_bps: Decimal
    total_cost_bps: Decimal


class RecommendationCostService:
    def estimate(self, symbol: str) -> CostBreakdown:
        est = cost_estimator.estimate_cost(symbol)
        return CostBreakdown(
            fee_bps=est.fee_bps,
            spread_bps=est.spread_bps,
            slippage_bps=est.slippage_bps,
            uncertainty_buffer_bps=est.uncertainty_buffer_bps,
            total_cost_bps=est.total_cost_bps,
        )


recommendation_cost_service = RecommendationCostService()
