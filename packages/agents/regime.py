from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from pydantic import BaseModel

from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.strategy_config import default_strategy_config


class RegimeResult(BaseModel):
    """Point-in-time regime classification with full audit lineage. `confidence` is a
    heuristic score derived from how far the deciding feature is past its threshold — it is
    NOT a calibrated statistical probability (same convention as AgentSignal.confidence_type =
    "HEURISTIC_SCORE"), and must never be treated as one downstream (Master Plan principle 7)."""

    regime: MarketRegime
    confidence: Decimal
    regime_version: str
    calculated_at: datetime       # wall-clock time this classification was actually computed
    feature_timestamp: datetime   # the as_of_time the underlying features were computed from
    reason_codes: List[str]


class MarketRegimeAgent:
    """Classifies market regime into TREND_UP, TREND_DOWN, SIDEWAYS, HIGH_VOLATILITY, etc."""

    def __init__(self, agent_id: str = "regime_agent_v1", version: str = "1.0.0"):
        self._agent_id = agent_id
        self._version = version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return "Market Regime Agent"

    @property
    def version(self) -> str:
        return self._version

    def classify_regime(self, context: AgentEvaluationContext) -> MarketRegime:
        vals = context.feature_snapshot.values
        cfg = context.strategy_config or default_strategy_config

        adx = vals.get("adx_14")
        ema_slope = vals.get("ema_20_slope")
        vol = vals.get("volatility_20")

        if adx is None or ema_slope is None:
            return MarketRegime.UNKNOWN

        adx_dec = Decimal(str(adx))
        slope_dec = Decimal(str(ema_slope))
        vol_dec = Decimal(str(vol)) if vol is not None else Decimal("0")

        if vol_dec > cfg.regime_high_vol_threshold:
            return MarketRegime.HIGH_VOLATILITY

        if adx_dec >= cfg.regime_adx_trend_threshold:
            if slope_dec > cfg.regime_slope_up_threshold:
                return MarketRegime.TREND_UP
            elif slope_dec < cfg.regime_slope_down_threshold:
                return MarketRegime.TREND_DOWN

        return MarketRegime.SIDEWAYS

    def classify_regime_detailed(self, context: AgentEvaluationContext) -> RegimeResult:
        """Same classification as classify_regime (single source of truth — this calls it
        directly rather than re-implementing the thresholds) plus the audit metadata Checkpoint
        2's Strategy Router and evidence lineage need: confidence, version, and *why*."""
        regime = self.classify_regime(context)

        vals = context.feature_snapshot.values
        cfg = context.strategy_config or default_strategy_config
        adx = vals.get("adx_14")
        vol = vals.get("volatility_20")

        reason_codes: List[str]
        confidence: Decimal

        if regime == MarketRegime.UNKNOWN:
            reason_codes = ["INSUFFICIENT_FEATURE_DATA"]
            confidence = Decimal("0.0")
        elif regime == MarketRegime.HIGH_VOLATILITY:
            vol_dec = Decimal(str(vol))
            margin = (vol_dec - cfg.regime_high_vol_threshold) / cfg.regime_high_vol_threshold
            confidence = Decimal("0.5") + margin
            reason_codes = ["VOLATILITY_ABOVE_THRESHOLD"]
        elif regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
            adx_dec = Decimal(str(adx))
            margin = (adx_dec - cfg.regime_adx_trend_threshold) / cfg.regime_adx_trend_threshold
            confidence = Decimal("0.5") + margin
            direction = "UP" if regime == MarketRegime.TREND_UP else "DOWN"
            reason_codes = ["ADX_ABOVE_TREND_THRESHOLD", f"EMA_SLOPE_{direction}"]
        else:  # SIDEWAYS: nothing else fired, no strong directional or volatility signal
            confidence = Decimal("0.5")
            reason_codes = ["NO_STRONG_TREND_OR_VOLATILITY_SIGNAL"]

        confidence = max(Decimal("0.0"), min(Decimal("1.0"), confidence))

        return RegimeResult(
            regime=regime,
            confidence=confidence,
            regime_version=self._version,
            calculated_at=datetime.now(timezone.utc),
            feature_timestamp=context.as_of_time,
            reason_codes=reason_codes,
        )
