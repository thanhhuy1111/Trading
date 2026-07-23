"""Checkpoint 2 mandatory tests: invalid OHLC / not-yet-closed / future-timestamp candles are
rejected, and gaps are correctly attributed to feature-lookback vs. label-horizon windows."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.market_data.historical_quality import (
    DatasetQualityStatus,
    filter_valid_decision_points,
    gap_overlaps_window,
    validate_historical_series,
)
from packages.market_data.models import Candle, Timeframe

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candle(
    hour_offset: int, *, is_closed: bool = True,
    price: Decimal = Decimal("100"), volume: Decimal = Decimal("10"),
) -> Candle:
    open_t = T0 + timedelta(hours=hour_offset)
    close_t = open_t + timedelta(minutes=59, seconds=59)
    return Candle(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1,
        exchange_timestamp=close_t, open_time=open_t, close_time=close_t,
        open_price=price, high_price=price + Decimal("5"), low_price=price - Decimal("5"),
        close_price=price, volume=volume, is_closed=is_closed,
    )


def test_clean_series_is_validated() -> None:
    candles = [_candle(i) for i in range(24)]
    as_of = T0 + timedelta(hours=30)
    clean, report = validate_historical_series(candles, Timeframe.H1, as_of=as_of)
    assert len(clean) == 24
    assert report.status == DatasetQualityStatus.VALIDATED
    assert report.gaps == []


def test_invalid_ohlc_high_is_rejected() -> None:
    bad = _candle(0)
    bad = bad.model_copy(update={"high_price": Decimal("50")})  # high < open/close
    good = [_candle(i) for i in range(1, 5)]
    clean, report = validate_historical_series([bad, *good], Timeframe.H1, as_of=T0 + timedelta(hours=10))
    assert report.invalid_ohlc_count == 1
    assert all(c.close_time != bad.close_time for c in clean)


def test_negative_volume_is_rejected() -> None:
    bad = _candle(0).model_copy(update={"volume": Decimal("1")})
    object.__setattr__(bad, "volume", Decimal("-5"))  # bypass model validation to test the series-level check
    good = [_candle(i) for i in range(1, 5)]
    clean, report = validate_historical_series([bad, *good], Timeframe.H1, as_of=T0 + timedelta(hours=10))
    assert report.negative_volume_count == 1


def test_not_yet_closed_candle_is_dropped() -> None:
    open_candle = _candle(5, is_closed=False)
    candles = [_candle(i) for i in range(5)] + [open_candle]
    clean, report = validate_historical_series(candles, Timeframe.H1, as_of=T0 + timedelta(hours=10))
    assert report.partial_candle_count == 1
    assert all(c.close_time != open_candle.close_time for c in clean)


def test_future_timestamp_candle_is_rejected() -> None:
    as_of = T0 + timedelta(hours=5)
    future = _candle(20)  # well beyond as_of
    candles = [_candle(i) for i in range(5)] + [future]
    clean, report = validate_historical_series(candles, Timeframe.H1, as_of=as_of)
    assert report.future_timestamp_count == 1
    assert all(c.close_time != future.close_time for c in clean)


def test_duplicate_timestamp_is_detected() -> None:
    c1 = _candle(0)
    c2 = _candle(0)  # exact duplicate close_time
    candles = [c1, c2, *[_candle(i) for i in range(1, 5)]]
    clean, report = validate_historical_series(candles, Timeframe.H1, as_of=T0 + timedelta(hours=10))
    assert report.duplicate_timestamps == 1
    assert len(clean) == 5


def test_small_gap_marks_degraded_not_rejected() -> None:
    # 20 candles then a 3-hour gap (hours 20,21,22 missing) then 20 more: well under the 10%
    # severe threshold (3 missing / 43 expected ~= 7%).
    first = [_candle(i) for i in range(20)]
    second = [_candle(i) for i in range(23, 43)]
    clean, report = validate_historical_series(first + second, Timeframe.H1, as_of=T0 + timedelta(hours=50))
    assert report.status == DatasetQualityStatus.DEGRADED
    assert report.missing_candle_count == 3
    assert len(report.gaps) == 1


def test_severe_gap_rejects_the_dataset() -> None:
    # 5 clean candles then a 100-hour gap: missing >> 10% of expected total.
    first = [_candle(i) for i in range(5)]
    second = [_candle(i) for i in range(105, 110)]
    clean, report = validate_historical_series(first + second, Timeframe.H1, as_of=T0 + timedelta(hours=120))
    assert report.status == DatasetQualityStatus.REJECTED


def test_wrong_spacing_detected_when_not_interval_multiple() -> None:
    c1 = _candle(0)
    c2 = c1.model_copy(update={
        "open_time": c1.open_time + timedelta(minutes=90),
        "close_time": c1.close_time + timedelta(minutes=90),
    })
    candles = [c1, c2, *[_candle(i) for i in range(2, 6)]]
    clean, report = validate_historical_series(candles, Timeframe.H1, as_of=T0 + timedelta(hours=10))
    assert report.wrong_spacing_count >= 1


def test_gap_overlaps_window_true_and_false() -> None:
    from packages.market_data.historical_quality import GapRecord

    gap = GapRecord(
        after_close_time=T0 + timedelta(hours=10), before_close_time=T0 + timedelta(hours=15), missing_count=4,
    )
    assert gap_overlaps_window([gap], T0 + timedelta(hours=9), T0 + timedelta(hours=11)) is True
    assert gap_overlaps_window([gap], T0 + timedelta(hours=1), T0 + timedelta(hours=2)) is False


def test_gap_in_feature_lookback_invalidates_decision_point() -> None:
    from packages.market_data.historical_quality import GapRecord

    decision_time = T0 + timedelta(hours=50)
    gap = GapRecord(
        after_close_time=decision_time - timedelta(hours=10),
        before_close_time=decision_time - timedelta(hours=5), missing_count=4,
    )
    results = filter_valid_decision_points(
        [decision_time], [gap], feature_lookback=timedelta(hours=20), label_horizon=timedelta(hours=5),
    )
    assert results[0].valid is False
    assert "GAP_IN_FEATURE_LOOKBACK" in results[0].reason_codes


def test_gap_in_label_horizon_invalidates_decision_point() -> None:
    from packages.market_data.historical_quality import GapRecord

    decision_time = T0 + timedelta(hours=50)
    gap = GapRecord(
        after_close_time=decision_time + timedelta(hours=1),
        before_close_time=decision_time + timedelta(hours=3), missing_count=1,
    )
    results = filter_valid_decision_points(
        [decision_time], [gap], feature_lookback=timedelta(hours=20), label_horizon=timedelta(hours=5),
    )
    assert results[0].valid is False
    assert "GAP_IN_LABEL_HORIZON" in results[0].reason_codes


def test_gap_outside_both_windows_does_not_invalidate() -> None:
    from packages.market_data.historical_quality import GapRecord

    decision_time = T0 + timedelta(hours=50)
    far_gap = GapRecord(after_close_time=T0, before_close_time=T0 + timedelta(hours=2), missing_count=2)
    results = filter_valid_decision_points(
        [decision_time], [far_gap], feature_lookback=timedelta(hours=20), label_horizon=timedelta(hours=5),
    )
    assert results[0].valid is True
    assert results[0].reason_codes == []


def test_empty_series_is_rejected() -> None:
    clean, report = validate_historical_series([], Timeframe.H1)
    assert report.status == DatasetQualityStatus.REJECTED
    assert clean == []
