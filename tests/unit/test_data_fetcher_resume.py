"""Resumable fetch must pick up from a partial checkpoint instead of refetching from scratch,
and must never leave a stale .partial.json behind after a successful completion. No real
network calls — httpx.Client.get is monkeypatched with a fake, deterministic kline server."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from packages.market_data.models import Timeframe
from packages.research import data_fetcher


def _kline_row(open_ms: int, close_ms: int, price: str = "100.0") -> list:
    return [open_ms, price, price, price, price, "10.0", close_ms, "1000.0", 5, "5.0", "500.0", "0"]


class _FakeResponse:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return self._rows


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetcher, "CACHE_DIR", tmp_path)
    yield tmp_path


def test_resume_picks_up_from_partial_checkpoint_not_from_scratch(tmp_path):
    symbol, tf = "BTC/USDT", Timeframe.H1
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=5)

    # Pre-seed a partial checkpoint as if 2 hourly candles were already fetched and the
    # process was interrupted before fetching the rest.
    hour_ms = 3600_000
    first_open_ms = int(start.timestamp() * 1000)
    partial_candles = [
        data_fetcher._candle_to_json(data_fetcher._parse_kline_row(
            _kline_row(first_open_ms + i * hour_ms, first_open_ms + (i + 1) * hour_ms - 1), "binance", symbol, tf,
        ))
        for i in range(2)
    ]
    next_cursor_ms = first_open_ms + 2 * hour_ms
    partial_path = data_fetcher._partial_cache_path(symbol, tf)
    with open(partial_path, "w") as f:
        json.dump({
            "symbol": symbol, "timeframe": tf.value,
            "next_cursor_ms": next_cursor_ms, "candles": partial_candles,
        }, f)

    # The fake server only ever gets asked to resume from next_cursor_ms onward — if the
    # resume logic ignored the checkpoint and asked for `start` again, this assertion fails.
    requested_start_times = []

    def fake_get(self, url, params=None):
        requested_start_times.append(params["startTime"])
        remaining_hours = 3  # hours 2,3,4 remain after the 2 pre-seeded ones
        rows = [
            _kline_row(next_cursor_ms + i * hour_ms, next_cursor_ms + (i + 1) * hour_ms - 1)
            for i in range(remaining_hours)
        ]
        return _FakeResponse(rows)

    with patch("httpx.Client.get", fake_get):
        result = data_fetcher.load_or_fetch_resumable(symbol, tf, start, end, request_pause_seconds=0)

    assert requested_start_times == [next_cursor_ms]  # resumed, did not re-request from `start`
    assert len(result) == 5  # 2 pre-seeded + 3 newly fetched
    assert not partial_path.exists()  # cleaned up after successful completion
    assert data_fetcher._cache_path(symbol, tf).exists()  # finalized into the real cache


def test_successful_fetch_from_scratch_leaves_no_partial_file(tmp_path):
    symbol, tf = "ETH/USDT", Timeframe.H1
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    hour_ms = 3600_000
    start_ms = int(start.timestamp() * 1000)

    def fake_get(self, url, params=None):
        rows = [_kline_row(start_ms, start_ms + hour_ms - 1)]
        return _FakeResponse(rows)

    with patch("httpx.Client.get", fake_get):
        result = data_fetcher.load_or_fetch_resumable(symbol, tf, start, end, request_pause_seconds=0)

    assert len(result) == 1
    assert not data_fetcher._partial_cache_path(symbol, tf).exists()


def test_existing_final_cache_short_circuits_without_any_network_call(tmp_path):
    symbol, tf = "SOL/USDT", Timeframe.H1
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    def fail_get(self, url, params=None):
        raise AssertionError("should not be called — final cache already exists")

    # First call actually fetches and writes the final cache.
    def fake_get(self, url, params=None):
        start_ms = int(start.timestamp() * 1000)
        return _FakeResponse([_kline_row(start_ms, start_ms + 3600_000 - 1)])

    with patch("httpx.Client.get", fake_get):
        data_fetcher.load_or_fetch_resumable(symbol, tf, start, end, request_pause_seconds=0)

    # Second call must short-circuit on the finalized cache without touching the network.
    with patch("httpx.Client.get", fail_get):
        result = data_fetcher.load_or_fetch_resumable(symbol, tf, start, end, request_pause_seconds=0)
    assert len(result) == 1
