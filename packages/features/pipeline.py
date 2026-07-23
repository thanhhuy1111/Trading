from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import uuid4

from packages.features.calculators.breakout import register_breakout_calculators
from packages.features.calculators.momentum import register_momentum_calculators
from packages.features.calculators.returns import register_returns_calculators
from packages.features.calculators.reversion import register_reversion_calculators
from packages.features.calculators.trend import register_trend_calculators
from packages.features.calculators.volatility import register_volatility_calculators
from packages.features.calculators.volume import register_volume_calculators
from packages.features.models import (
    FeatureComputationRequest,
    FeatureContext,
    FeatureLineage,
    FeatureSnapshot,
)
from packages.features.registry import feature_registry
from packages.features.validator import feature_validator
from packages.market_data.models import Candle

# Initialize standard calculators in global registry
register_returns_calculators()
register_trend_calculators()
register_momentum_calculators()
register_volatility_calculators()
register_volume_calculators()
register_reversion_calculators()
register_breakout_calculators()


class FeaturePipeline:
    """Feature Computation Pipeline executing feature calculators with temporal invariant guarantees."""

    def compute(
        self,
        request: FeatureComputationRequest,
        candles: List[Candle]
    ) -> FeatureSnapshot:
        now = datetime.now(timezone.utc)
        as_of_time = request.as_of_time

        # Temporal filter: strict filtering to prevent lookahead leakage
        closed_candles = [c for c in candles if c.is_closed and c.close_time <= as_of_time]
        closed_candles.sort(key=lambda x: x.open_time)

        context = FeatureContext(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            as_of_time=as_of_time,
            data_quality_status="HEALTHY"
        )

        computed_values: Dict[str, Optional[Decimal | int | bool]] = {}
        calc_versions: Dict[str, str] = {}

        # Default standard feature list for MVP
        standard_features = [
            "return_1p", "return_3p", "return_5p", "high_low_range",
            "sma_10", "sma_20", "ema_10", "ema_20", "ema_20_slope", "adx_14",
            "rsi_14", "atr_14", "volatility_20", "volume_sma_20", "relative_volume_20",
            "zscore_20", "bollinger_pos_20", "donchian_breakout_20"
        ]

        for fname in standard_features:
            calc = feature_registry.get_calculator(fname)
            if calc:
                val_obj = calc.calculate(closed_candles, context)
                computed_values[fname] = val_obj.value if val_obj.is_valid else None
                calc_versions[fname] = calc.version
            else:
                computed_values[fname] = None

        quality_status, quality_issues = feature_validator.validate_snapshot(computed_values, as_of_time)

        lookback_start = closed_candles[0].open_time if closed_candles else as_of_time
        lookback_end = closed_candles[-1].close_time if closed_candles else as_of_time

        lineage = FeatureLineage(
            source_exchange=request.exchange,
            source_symbol=request.symbol,
            source_timeframe=request.timeframe.value,
            candle_count_used=len(closed_candles),
            oldest_candle_timestamp=lookback_start,
            newest_candle_timestamp=lookback_end,
            calculator_versions=calc_versions
        )

        return FeatureSnapshot(
            snapshot_id=uuid4(),
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            feature_set=request.feature_set,
            feature_set_version="1.0.0",
            event_time=lookback_end,
            as_of_time=as_of_time,
            computed_at=now,
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            values=computed_values,
            quality_status=quality_status,
            quality_issues=quality_issues,
            source_data_version="v1",
            lineage=lineage,
            schema_version=1
        )


feature_pipeline = FeaturePipeline()
