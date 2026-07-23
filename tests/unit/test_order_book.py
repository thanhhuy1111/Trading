from datetime import datetime, timezone
from decimal import Decimal

from packages.market_data.models import OrderBookDelta, OrderBookLevel, OrderBookSnapshot
from packages.market_data.order_book import LocalOrderBookService


def test_order_book_snapshot_and_delta():
    now = datetime.now(timezone.utc)
    service = LocalOrderBookService("BTC/USDT")

    snapshot = OrderBookSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        sequence_id=100,
        bids=[OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("1.0"))],
        asks=[OrderBookLevel(price=Decimal("65002.00"), quantity=Decimal("2.0"))],
        exchange_timestamp=now
    )
    service.apply_snapshot(snapshot)
    assert service.get_best_bid() == Decimal("65000.00")
    assert service.get_best_ask() == Decimal("65002.00")

    # Apply valid sequence delta
    delta = OrderBookDelta(
        exchange="binance",
        symbol="BTC/USDT",
        first_update_id=101,
        final_update_id=101,
        bids=[OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("1.5"))],
        asks=[],
        exchange_timestamp=now
    )
    success = service.apply_delta(delta)
    assert success is True
    assert service.get_best_bid() == Decimal("65001.00")


def test_order_book_sequence_gap_detection():
    now = datetime.now(timezone.utc)
    service = LocalOrderBookService("BTC/USDT")

    snapshot = OrderBookSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        sequence_id=100,
        bids=[OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("1.0"))],
        asks=[OrderBookLevel(price=Decimal("65002.00"), quantity=Decimal("2.0"))],
        exchange_timestamp=now
    )
    service.apply_snapshot(snapshot)

    # Gap delta (105 instead of 101)
    gap_delta = OrderBookDelta(
        exchange="binance",
        symbol="BTC/USDT",
        first_update_id=105,
        final_update_id=105,
        bids=[],
        asks=[],
        exchange_timestamp=now
    )
    success = service.apply_delta(gap_delta)
    assert success is False
    assert service.status.value == "RESYNCING"
