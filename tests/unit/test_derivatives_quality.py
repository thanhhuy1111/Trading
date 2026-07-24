"""Pure, network-free tests for packages.market_data.derivatives_quality -- the basis
computation and data-quality status logic behind the new futures/derivatives data
connector (Multi-Agent Trading Advisor plan, Phase 1: Data Foundation)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.market_data.derivatives_quality import compute_data_quality_status, compute_futures_basis_bps
from packages.market_data.models import DataQualityStatus

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_futures_basis_bps_computes_premium_correctly() -> None:
    # Futures at 50500, spot at 50000 -> +100bps premium.
    basis = compute_futures_basis_bps(Decimal("50500"), Decimal("50000"))
    assert basis == Decimal("100")


def test_futures_basis_bps_none_when_mark_price_missing() -> None:
    assert compute_futures_basis_bps(None, Decimal("50000")) is None


def test_futures_basis_bps_none_when_spot_price_missing() -> None:
    assert compute_futures_basis_bps(Decimal("50500"), None) is None


def test_futures_basis_bps_none_when_spot_price_is_zero() -> None:
    assert compute_futures_basis_bps(Decimal("50500"), Decimal("0")) is None


def test_data_quality_all_succeeded_and_fresh_is_healthy() -> None:
    status, reasons = compute_data_quality_status(
        {"mark_and_index_price": True, "open_interest": True}, as_of=NOW, now=NOW,
    )
    assert status == DataQualityStatus.HEALTHY
    assert reasons == []


def test_data_quality_all_failed_is_unhealthy() -> None:
    status, reasons = compute_data_quality_status(
        {"mark_and_index_price": False, "open_interest": False}, as_of=None, now=NOW,
    )
    assert status == DataQualityStatus.UNHEALTHY
    assert "ALL_DERIVATIVES_SUB_FETCHES_FAILED" in reasons


def test_data_quality_partial_success_is_degraded() -> None:
    status, reasons = compute_data_quality_status(
        {"mark_and_index_price": True, "open_interest": False}, as_of=NOW, now=NOW,
    )
    assert status == DataQualityStatus.DEGRADED
    assert any("PARTIAL_DATA_MISSING" in r for r in reasons)
    assert "open_interest" in reasons[0]


def test_data_quality_stale_when_older_than_staleness_window() -> None:
    old = NOW - timedelta(hours=20)  # > 2 * 8h default funding interval
    status, reasons = compute_data_quality_status(
        {"mark_and_index_price": True}, as_of=old, now=NOW,
    )
    assert status == DataQualityStatus.STALE
    assert "DERIVATIVES_DATA_STALE" in reasons


def test_data_quality_within_staleness_window_is_healthy_even_if_a_few_hours_old() -> None:
    slightly_old = NOW - timedelta(hours=4)  # well within 2 * 8h = 16h window
    status, _ = compute_data_quality_status({"mark_and_index_price": True}, as_of=slightly_old, now=NOW)
    assert status == DataQualityStatus.HEALTHY


def test_data_quality_stale_takes_priority_over_partial() -> None:
    """A snapshot that is BOTH partial (some sub-fetches failed) and stale (the ones that
    succeeded are too old) is reported STALE, not DEGRADED -- staleness is the more severe,
    more actionable signal for a caller deciding whether to trust this snapshot at all."""
    old = NOW - timedelta(hours=20)
    status, reasons = compute_data_quality_status(
        {"mark_and_index_price": True, "open_interest": False}, as_of=old, now=NOW,
    )
    assert status == DataQualityStatus.STALE
    assert any("PARTIAL_DATA_MISSING" in r for r in reasons)
    assert "DERIVATIVES_DATA_STALE" in reasons
