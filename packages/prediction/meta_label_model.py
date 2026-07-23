"""Meta-labeling: decide whether an already-produced primary signal is worth acting on.

This runs strictly AFTER direction/return prediction, on their real outputs -- it can only
narrow (never widen or invent) the set of tradeable candidates. `ThresholdMetaLabelModel`
is a deterministic, config-driven gate (not a second ML model) suitable while no trained
meta-labeler exists; the `MetaLabelModel` protocol lets a real secondary classifier be
swapped in later without touching callers.
"""

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


class MetaLabelDecision(BaseModel):
    accept: bool
    reason_codes: list[str]


class MetaLabelModel(Protocol):
    model_version: str

    def evaluate(
        self,
        probability_profit: Decimal,
        expected_net_return_bps: Decimal,
        expected_volatility_bps: Decimal,
    ) -> MetaLabelDecision: ...


class ThresholdMetaLabelModel:
    """Rejects candidates whose predicted edge is not meaningfully larger than the
    model's own predicted noise (volatility), independent of the opportunity-gate
    thresholds applied later in packages/recommendation.
    """

    model_version = "threshold_meta_label_v1"

    def __init__(self, min_return_to_volatility_ratio: Decimal = Decimal("0.10")) -> None:
        self._min_ratio = min_return_to_volatility_ratio

    def evaluate(
        self,
        probability_profit: Decimal,
        expected_net_return_bps: Decimal,
        expected_volatility_bps: Decimal,
    ) -> MetaLabelDecision:
        reasons: list[str] = []
        if expected_net_return_bps <= Decimal("0"):
            reasons.append("NON_POSITIVE_NET_RETURN")
        if expected_volatility_bps and expected_volatility_bps > Decimal("0"):
            ratio = expected_net_return_bps / expected_volatility_bps
            if ratio < self._min_ratio:
                reasons.append("RETURN_NOT_SIGNIFICANT_VS_VOLATILITY")
        return MetaLabelDecision(accept=(len(reasons) == 0), reason_codes=reasons)


threshold_meta_label_model = ThresholdMetaLabelModel()
