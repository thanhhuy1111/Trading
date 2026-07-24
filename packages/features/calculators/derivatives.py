"""Derivatives feature calculators (Multi-Agent Trading Advisor plan, Phase 2). Each mirrors
`packages.features.calculators.reversion.RollingZScoreCalculator`'s style -- small, inline
rolling-window math, no shared stats utility -- but operates on a `DerivativesSnapshot` history
instead of a `Candle` history. A calculator with fewer than `required_lookback` REAL (non-None)
values for its field in the window returns `is_valid=False` with `error_message
="INSUFFICIENT_HISTORY"` -- never a fabricated number, and distinguishable from a genuine data
error by `DerivativesFeaturePipeline` (which reports the snapshot as WARMING_UP, not DEGRADED,
for this specific reason)."""

import math
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple

from packages.features.derivatives_models import DerivativesFeatureContext
from packages.features.derivatives_registry import derivatives_feature_registry
from packages.features.models import FeatureDefinition, FeatureValue
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import Timeframe

INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


def _valid_series(snapshots: List[DerivativesSnapshot], field: str) -> List[Tuple[datetime, Decimal]]:
    """Sorted-ascending (timestamp, value) pairs for `field`, skipping any snapshot where it's
    None -- a snapshot missing this one metric (e.g. a PARTIAL fetch) doesn't disqualify the
    other real values around it."""
    pairs: List[Tuple[datetime, Decimal]] = [
        (s.exchange_timestamp, getattr(s, field))
        for s in snapshots
        if getattr(s, field) is not None
    ]
    pairs.sort(key=lambda p: p[0])
    return pairs


def _insufficient(name: str, version: str) -> FeatureValue:
    return FeatureValue(name=name, version=version, value=None, is_valid=False, error_message=INSUFFICIENT_HISTORY)


class FundingRateZScoreCalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"funding_rate_zscore_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "derivatives"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, snapshots: List[DerivativesSnapshot], context: DerivativesFeatureContext) -> FeatureValue:
        series = _valid_series(snapshots, "funding_rate")
        if len(series) < self.required_lookback:
            return _insufficient(self.name, self.version)

        window = [float(v) for _, v in series[-self.period:]]
        current = window[-1]
        mean = sum(window) / len(window)
        variance = sum((v - mean) ** 2 for v in window) / len(window)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return FeatureValue(name=self.name, version=self.version, value=Decimal("0"), is_valid=True)
        z = (current - mean) / std_dev
        return FeatureValue(name=self.name, version=self.version, value=Decimal(str(z)), is_valid=True)


class OpenInterestRateOfChangeCalculator:
    def __init__(self, period: int = 12, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"open_interest_roc_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "derivatives"

    @property
    def required_lookback(self) -> int:
        return self.period + 1  # need a point "period samples ago" plus the current one

    def calculate(self, snapshots: List[DerivativesSnapshot], context: DerivativesFeatureContext) -> FeatureValue:
        series = _valid_series(snapshots, "open_interest")
        if len(series) < self.required_lookback:
            return _insufficient(self.name, self.version)

        window = series[-self.required_lookback:]
        base_value = float(window[0][1])
        current_value = float(window[-1][1])
        if base_value == 0:
            return _insufficient(self.name, self.version)

        roc_pct = (current_value - base_value) / base_value * 100
        return FeatureValue(name=self.name, version=self.version, value=Decimal(str(roc_pct)), is_valid=True)


class FuturesBasisMomentumCalculator:
    def __init__(self, period: int = 6, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"futures_basis_momentum_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "derivatives"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, snapshots: List[DerivativesSnapshot], context: DerivativesFeatureContext) -> FeatureValue:
        series = _valid_series(snapshots, "futures_basis_bps")
        if len(series) < self.required_lookback:
            return _insufficient(self.name, self.version)

        window = series[-self.required_lookback:]
        base_value = window[0][1]
        current_value = window[-1][1]
        momentum_bps = current_value - base_value
        return FeatureValue(name=self.name, version=self.version, value=momentum_bps, is_valid=True)


def register_derivatives_calculators() -> None:
    funding_zscore = FundingRateZScoreCalculator(period=20)
    derivatives_feature_registry.register(
        FeatureDefinition(
            name=funding_zscore.name, version=funding_zscore.version, category=funding_zscore.category,
            description="Rolling funding-rate Z-score over 20 polled samples",
            required_lookback=funding_zscore.required_lookback,
            supported_timeframes=[Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="PARTIAL",
        ),
        funding_zscore,
    )

    oi_roc = OpenInterestRateOfChangeCalculator(period=12)
    derivatives_feature_registry.register(
        FeatureDefinition(
            name=oi_roc.name, version=oi_roc.version, category=oi_roc.category,
            description="Open interest percent rate-of-change over 12 polled samples",
            required_lookback=oi_roc.required_lookback,
            supported_timeframes=[Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="PARTIAL",
        ),
        oi_roc,
    )

    basis_momentum = FuturesBasisMomentumCalculator(period=6)
    derivatives_feature_registry.register(
        FeatureDefinition(
            name=basis_momentum.name, version=basis_momentum.version, category=basis_momentum.category,
            description="Futures basis (bps) change over 6 polled samples",
            required_lookback=basis_momentum.required_lookback,
            supported_timeframes=[Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="PARTIAL",
        ),
        basis_momentum,
    )
