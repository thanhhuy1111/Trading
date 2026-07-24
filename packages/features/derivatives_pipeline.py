"""Derivatives feature computation pipeline (Multi-Agent Trading Advisor plan, Phase 2).

A small parallel of `packages.features.pipeline.FeaturePipeline` -- not a branch inside it --
because that pipeline's `compute()`, `FeatureContext`, and `FeatureSnapshot` are hardcoded to
`Candle`-shaped inputs (`timeframe`, `candle_count_used`, ...), which don't fit a derivatives
snapshot history. Shares `FeatureQualityStatus`/`FeatureQualityIssue` from
`packages.features.models` as-is.

A calculator short of `required_lookback` real samples reports `INSUFFICIENT_HISTORY` (see
`packages.features.calculators.derivatives`); this pipeline treats that specific reason as
`WARMING_UP` (more data will fix it), distinct from any other calculator failure, which is
treated as `DEGRADED` (a real data-quality problem).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from packages.features.calculators.derivatives import INSUFFICIENT_HISTORY, register_derivatives_calculators
from packages.features.derivatives_models import (
    DerivativesFeatureComputationRequest,
    DerivativesFeatureContext,
    DerivativesFeatureLineage,
    DerivativesFeatureSnapshot,
)
from packages.features.derivatives_registry import derivatives_feature_registry
from packages.features.models import FeatureQualityIssue, FeatureQualityStatus
from packages.market_data.derivatives_models import DerivativesSnapshot

# Initialize derivatives calculators in the derivatives feature registry
register_derivatives_calculators()

STANDARD_DERIVATIVES_FEATURES = [
    "funding_rate_zscore_20",
    "open_interest_roc_12",
    "futures_basis_momentum_6",
]


class DerivativesFeaturePipeline:
    """Derivatives feature computation pipeline with temporal invariant guarantees."""

    def compute(
        self,
        request: DerivativesFeatureComputationRequest,
        snapshots: List[DerivativesSnapshot],
    ) -> DerivativesFeatureSnapshot:
        now = datetime.now(timezone.utc)
        as_of_time = request.as_of_time

        # Temporal filter: strict filtering to prevent lookahead leakage
        eligible = [s for s in snapshots if s.exchange_timestamp <= as_of_time]
        eligible.sort(key=lambda s: s.exchange_timestamp)

        context = DerivativesFeatureContext(
            exchange=request.exchange,
            symbol=request.symbol,
            as_of_time=as_of_time,
        )

        computed_values: Dict[str, Optional[Decimal | int | bool]] = {}
        calc_versions: Dict[str, str] = {}
        quality_issues: List[FeatureQualityIssue] = []
        any_warming_up = False
        any_degraded = False

        for fname in STANDARD_DERIVATIVES_FEATURES:
            calc = derivatives_feature_registry.get_calculator(fname)
            if calc is None:
                computed_values[fname] = None
                continue

            val_obj = calc.calculate(eligible, context)
            calc_versions[fname] = calc.version
            computed_values[fname] = val_obj.value if val_obj.is_valid else None

            if not val_obj.is_valid:
                is_warmup = val_obj.error_message == INSUFFICIENT_HISTORY
                any_warming_up = any_warming_up or is_warmup
                any_degraded = any_degraded or not is_warmup
                quality_issues.append(
                    FeatureQualityIssue(
                        feature_name=fname,
                        issue_type=val_obj.error_message or "UNKNOWN",
                        description=f"{fname} could not be computed: {val_obj.error_message}",
                        severity="WARNING" if is_warmup else "ERROR",
                        timestamp=now,
                    )
                )

        if any_degraded:
            quality_status = FeatureQualityStatus.DEGRADED
        elif any_warming_up:
            quality_status = FeatureQualityStatus.WARMING_UP
        else:
            quality_status = FeatureQualityStatus.VALID

        oldest = eligible[0].exchange_timestamp if eligible else None
        newest = eligible[-1].exchange_timestamp if eligible else None

        lineage = DerivativesFeatureLineage(
            source_exchange=request.exchange,
            source_symbol=request.symbol,
            sample_count=len(eligible),
            oldest_sample_timestamp=oldest,
            newest_sample_timestamp=newest,
            calculator_versions=calc_versions,
        )

        return DerivativesFeatureSnapshot(
            exchange=request.exchange,
            symbol=request.symbol,
            feature_set=request.feature_set,
            feature_set_version="1.0.0",
            as_of_time=as_of_time,
            computed_at=now,
            values=computed_values,
            quality_status=quality_status,
            quality_issues=quality_issues,
            lineage=lineage,
            schema_version=1,
        )


derivatives_feature_pipeline = DerivativesFeaturePipeline()
