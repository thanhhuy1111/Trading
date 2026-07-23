"""Paper fill safety: BUY never exceeds maximum_entry_price (F-09) and slippage is
modelled against the market reference, not clamped to the limit (F-08)."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.execution.models import ExchangeOrderRequest, SimulatorOrderType
from packages.paper.adapter import PaperExchangeAdapter


def _req(side: str, reference: Decimal, limit: Decimal, max_entry: Decimal) -> ExchangeOrderRequest:
    now = datetime.now(timezone.utc)
    return ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side=side,
        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
        quantity=Decimal("0.10"),
        limit_price=limit,
        maximum_entry_price=max_entry,
        reference_price=reference,
        remaining_approved_quantity=Decimal("0.10"),
        remaining_maximum_notional=Decimal("100000.00"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def test_buy_fill_never_exceeds_maximum_entry_price() -> None:
    # reference below the cap => slippage applies but stays within the cap
    ref = Decimal("50000.00")
    max_entry = Decimal("50050.00")  # 10 bps headroom (> 5 bps slippage)
    adapter = PaperExchangeAdapter()
    _, fills = asyncio.run(adapter.submit_order(_req("BUY", ref, max_entry, max_entry)))
    fill = fills[0]
    assert fill.price <= max_entry               # F-09 hard cap
    assert fill.price > ref                       # F-08 non-zero slippage vs. reference
    assert fill.price == ref * Decimal("1.0005")  # 5 bps model


def test_buy_fill_capped_when_reference_equals_cap() -> None:
    # reference == limit == cap: slippage would exceed the cap, so it must be clamped
    price = Decimal("50000.00")
    adapter = PaperExchangeAdapter()
    _, fills = asyncio.run(adapter.submit_order(_req("BUY", price, price, price)))
    assert fills[0].price <= price
    assert fills[0].price == price  # clamped exactly to the cap, never above


def test_sell_fill_has_slippage_and_respects_limit() -> None:
    ref = Decimal("50000.00")
    limit = Decimal("49000.00")  # minimum acceptable sell price, below reference
    adapter = PaperExchangeAdapter()
    _, fills = asyncio.run(adapter.submit_order(_req("SELL", ref, limit, Decimal("999999.00"))))
    fill = fills[0]
    assert fill.price < ref                       # F-08 slippage on sell
    assert fill.price >= limit                    # sell-limit semantics respected
    assert fill.price == ref * Decimal("0.9995")
