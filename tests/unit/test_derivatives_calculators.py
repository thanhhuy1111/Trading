"""Offline tests for the three derivatives feature calculators -- each covers an
insufficient-history case (never a fabricated number), a boundary case (exactly
`required_lookback` real samples), and a hand-computed-expected-value case that verifies the
actual math against an independently written reference computation, not just "it returns
something"."""

import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest

from packages.features.calculators.derivatives import (
    INSUFFICIENT_HISTORY,
    FundingRateZScoreCalculator,
    FuturesBasisMomentumCalculator,
    OpenInterestRateOfChangeCalculator,
)
from packages.features.derivatives_models import DerivativesFeatureContext
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONTEXT = DerivativesFeatureContext(
    exchange="binance_usdm_futures", symbol=SYMBOL, as_of_time=BASE_TIME + timedelta(days=1)
)


def _snapshots(
    values: Sequence[Optional[str]],
    field: str,
) -> List[DerivativesSnapshot]:
    out = []
    for i, v in enumerate(values):
        kwargs: Dict[str, Any] = {
            "exchange": "binance_usdm_futures",
            "symbol": SYMBOL,
            "data_quality_status": DataQualityStatus.HEALTHY,
            "exchange_timestamp": BASE_TIME + timedelta(minutes=5 * i),
        }
        if v is not None:
            kwargs[field] = Decimal(v)
        out.append(DerivativesSnapshot(**kwargs))
    return out


# --- FundingRateZScoreCalculator (period=20) ---------------------------------------------


def test_funding_rate_zscore_insufficient_history() -> None:
    calc = FundingRateZScoreCalculator(period=20)
    snapshots = _snapshots(["0.0001"] * 19, "funding_rate")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is False
    assert result.value is None
    assert result.error_message == INSUFFICIENT_HISTORY


def test_funding_rate_zscore_boundary_exact_lookback() -> None:
    calc = FundingRateZScoreCalculator(period=20)
    snapshots = _snapshots(["0.0001"] * 19 + ["0.0005"], "funding_rate")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is True
    assert result.value is not None


def test_funding_rate_zscore_matches_reference_computation() -> None:
    calc = FundingRateZScoreCalculator(period=20)
    raw = [0.0] * 19 + [0.02]
    snapshots = _snapshots([str(v) for v in raw], "funding_rate")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is True

    mean = statistics.fmean(raw)
    std_dev = statistics.pstdev(raw)
    expected_z = (raw[-1] - mean) / std_dev
    assert float(result.value) == pytest.approx(expected_z, rel=1e-9)  # type: ignore[arg-type]


def test_funding_rate_zscore_zero_variance_returns_zero() -> None:
    calc = FundingRateZScoreCalculator(period=20)
    snapshots = _snapshots(["0.0001"] * 20, "funding_rate")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is True
    assert result.value == Decimal("0")


def test_funding_rate_zscore_skips_none_values_when_counting_history() -> None:
    calc = FundingRateZScoreCalculator(period=20)
    values: List[Optional[str]] = ["0.0001"] * 19 + [None]  # only 19 real values
    snapshots = _snapshots(values, "funding_rate")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is False
    assert result.error_message == INSUFFICIENT_HISTORY


# --- OpenInterestRateOfChangeCalculator (period=12, required_lookback=13) --------------------


def test_open_interest_roc_insufficient_history() -> None:
    calc = OpenInterestRateOfChangeCalculator(period=12)
    snapshots = _snapshots(["1000"] * 12, "open_interest")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is False
    assert result.error_message == INSUFFICIENT_HISTORY


def test_open_interest_roc_boundary_and_hand_computed_value() -> None:
    calc = OpenInterestRateOfChangeCalculator(period=12)
    values = ["1000"] * 12 + ["1100"]  # exactly required_lookback=13 samples
    snapshots = _snapshots(values, "open_interest")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is True
    assert float(result.value) == pytest.approx(10.0, rel=1e-9)  # type: ignore[arg-type]


def test_open_interest_roc_zero_base_is_insufficient_not_a_crash() -> None:
    calc = OpenInterestRateOfChangeCalculator(period=12)
    values = ["0"] * 12 + ["50"]
    snapshots = _snapshots(values, "open_interest")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is False
    assert result.error_message == INSUFFICIENT_HISTORY


# --- FuturesBasisMomentumCalculator (period=6, required_lookback=7) --------------------------


def test_futures_basis_momentum_insufficient_history() -> None:
    calc = FuturesBasisMomentumCalculator(period=6)
    snapshots = _snapshots(["10"] * 6, "futures_basis_bps")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is False
    assert result.error_message == INSUFFICIENT_HISTORY


def test_futures_basis_momentum_boundary_and_exact_decimal_value() -> None:
    calc = FuturesBasisMomentumCalculator(period=6)
    values = ["10"] * 6 + ["25"]  # exactly required_lookback=7 samples
    snapshots = _snapshots(values, "futures_basis_bps")
    result = calc.calculate(snapshots, CONTEXT)
    assert result.is_valid is True
    assert result.value == Decimal("15")  # exact Decimal subtraction, no float rounding
