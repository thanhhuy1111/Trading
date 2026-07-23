"""Spacing diagnostics must classify anomalies, never silently drop the explanation."""

import json
from datetime import datetime, timedelta, timezone

from packages.market_data.models import Timeframe
from packages.research import data_fetcher, diagnose_spacing


def _write_fake_cache(tmp_path, symbol, timeframe, candles_json, monkeypatch):
    monkeypatch.setattr(data_fetcher, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(diagnose_spacing, "_cache_path", data_fetcher._cache_path)
    path = data_fetcher._cache_path(symbol, timeframe)
    with open(path, "w") as f:
        json.dump({"symbol": symbol, "timeframe": timeframe.value, "candles": candles_json}, f)
    return path


def _candle_json(close_time: datetime, price: str = "100.0") -> dict:
    open_time = close_time - timedelta(hours=1) + timedelta(milliseconds=1)
    return {
        "exchange": "binance", "symbol": "BTC/USDT", "timeframe": "1h",
        "open_time": open_time.isoformat(), "close_time": close_time.isoformat(),
        "open_price": price, "high_price": price, "low_price": price, "close_price": price,
        "volume": "10.0", "quote_volume": "1000.0", "trades_count": 5,
    }


def test_clean_series_produces_no_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose_spacing, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(diagnose_spacing, "TIMEFRAMES", [Timeframe.H1])
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [_candle_json(t0 + timedelta(hours=i)) for i in range(5)]
    _write_fake_cache(tmp_path, "BTC/USDT", Timeframe.H1, candles, monkeypatch)

    diags = diagnose_spacing.diagnose()
    assert diags == []


def test_misaligned_candle_is_classified_source_anomaly(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose_spacing, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(diagnose_spacing, "TIMEFRAMES", [Timeframe.H1])
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [_candle_json(t0 + timedelta(hours=i)) for i in range(3)]
    # Insert a misaligned candle between index 3 and 4 (not a page-boundary index).
    candles.append(_candle_json(t0 + timedelta(hours=3, minutes=40)))
    candles.append(_candle_json(t0 + timedelta(hours=5)))
    _write_fake_cache(tmp_path, "BTC/USDT", Timeframe.H1, candles, monkeypatch)

    diags = diagnose_spacing.diagnose()
    assert len(diags) >= 1
    assert all(d.classification != "" for d in diags)
    assert any(d.classification == "SOURCE_ANOMALY" for d in diags)


def test_exact_gap_multiple_is_valid_exchange_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose_spacing, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(diagnose_spacing, "TIMEFRAMES", [Timeframe.H1])
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [_candle_json(t0 + timedelta(hours=i)) for i in range(3)]
    candles.append(_candle_json(t0 + timedelta(hours=6)))  # exact 3-bar gap, no misalignment
    _write_fake_cache(tmp_path, "BTC/USDT", Timeframe.H1, candles, monkeypatch)

    diags = diagnose_spacing.diagnose()
    assert len(diags) == 1
    assert diags[0].classification == "VALID_EXCHANGE_INTERVAL"


def test_pagination_boundary_index_is_classified_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnose_spacing, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(diagnose_spacing, "TIMEFRAMES", [Timeframe.H1])
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Build exactly 1000 clean candles then one misaligned candle right at the page boundary.
    candles = [_candle_json(t0 + timedelta(hours=i)) for i in range(1000)]
    candles.append(_candle_json(t0 + timedelta(hours=999, minutes=40)))
    _write_fake_cache(tmp_path, "BTC/USDT", Timeframe.H1, candles, monkeypatch)

    diags = diagnose_spacing.diagnose()
    assert len(diags) >= 1
    assert diags[0].classification == "PAGINATION_BOUNDARY"
