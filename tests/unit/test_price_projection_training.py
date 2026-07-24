"""packages/retraining/price_projection.py's gate is two-sided by design: it must be able
to say yes when a real, learnable relationship exists, and it must say no when there isn't
one. Testing only the reject path (as would be tempting, since that's the "safe" direction)
would leave the approve path completely unverified -- exactly the gap
tests/unit/test_research_gate.py was written to avoid for the campaign's gate, and the same
discipline applies here."""

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from packages.market_data.models import Candle, Timeframe
from packages.retraining.price_projection import HORIZONS, build_rows, train

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def _candle(open_time: datetime, close_price: Decimal) -> Candle:
    return Candle(
        exchange="binance", symbol=SYMBOL, exchange_timestamp=open_time, open_time=open_time,
        close_time=open_time + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1,
        open_price=close_price, high_price=close_price + Decimal("5"), low_price=close_price - Decimal("5"),
        close_price=close_price, volume=Decimal("100"), is_closed=True,
    )


def _smooth_trending_candles(n: int, segment_len: int = 20) -> List[Candle]:
    """Deterministic, low-noise alternating up/down trends -- no randomness at all, so the
    relationship between recent slope and near-future direction is genuinely, strongly
    learnable (unlike real noisy market data): within any sustained trend segment, "the
    price has been rising" really does predict "the price keeps rising for the next few
    bars," almost by construction. segment_len is deliberately short relative to a
    WalkForwardRunner fold's ~200-bar span (at n=600, num_folds=3) so every fold's
    train/validation/test window contains multiple complete up/down cycles -- a segment
    length close to or longer than a fold's own span would let a fold's train window land
    on a single direction while its test window lands on the opposite one, which is a
    fixture-construction problem, not a real generalization failure of the gate."""
    candles = []
    price = Decimal("50000")
    direction = 1
    for i in range(n):
        if i > 0 and i % segment_len == 0:
            direction *= -1
        price += Decimal(direction) * Decimal("15")
        candles.append(_candle(T0 + timedelta(hours=i), price))
    return candles


def _random_walk_candles(n: int, seed: int = 42) -> List[Candle]:
    """A true random walk: each step is IID noise with zero mean, no autocorrelation. No
    feature computed from past prices has any real relationship with the future step -- the
    gate must reject every horizon against this."""
    rng = random.Random(seed)
    candles = []
    price = Decimal("50000")
    for i in range(n):
        step = Decimal(str(round(rng.uniform(-40, 40), 2)))
        price = max(Decimal("1000"), price + step)
        candles.append(_candle(T0 + timedelta(hours=i), price))
    return candles


def test_build_rows_never_guesses_a_missing_feature_or_forward_return():
    candles = _smooth_trending_candles(60)
    rows = build_rows(candles, SYMBOL, Timeframe.H1)
    assert len(rows) > 0
    for row in rows:
        assert all(f is not None for f in row.features)
        # the last few rows can't have a full 12-bar-ahead forward return yet
    last_row = rows[-1]
    assert last_row.forward_returns[HORIZONS[-1]] is None


def test_gate_approves_at_least_one_horizon_for_a_genuine_learnable_signal():
    candles = _smooth_trending_candles(600)
    result = train(candles, SYMBOL, Timeframe.H1)

    approved = {h: r for h, r in result.horizons.items() if r.approved}
    assert approved, f"expected at least one approved horizon on a clean trending signal, got: {result.horizons}"

    for h, r in approved.items():
        assert r.oos_mape is not None and r.naive_oos_mape is not None
        assert r.oos_mape < r.naive_oos_mape, f"horizon {h} approved but doesn't actually beat naive MAPE"
        assert r.oos_directional_accuracy is not None and r.oos_directional_accuracy >= 0.55
        assert r.coefficients is not None and r.intercept is not None
        assert len(r.coefficients) == len(result.feature_names)


def test_gate_rejects_every_horizon_for_pure_random_walk_noise():
    candles = _random_walk_candles(600)
    result = train(candles, SYMBOL, Timeframe.H1)

    for h, r in result.horizons.items():
        assert not r.approved, f"horizon {h} was approved on pure random-walk noise: {r}"
        assert r.coefficients is None
        assert r.intercept is None
        assert r.reason != "APPROVED"


def test_insufficient_data_is_reported_honestly_not_silently_skipped():
    candles = _smooth_trending_candles(30)  # far too little for any fold to have train+val+test
    result = train(candles, SYMBOL, Timeframe.H1)
    for r in result.horizons.values():
        assert not r.approved
        assert r.reason == "INSUFFICIENT_DATA"


def test_forming_candle_cannot_change_training_rows_or_result() -> None:
    candles = _smooth_trending_candles(80)
    cutoff = candles[-1].close_time + timedelta(seconds=1)
    forming = _candle(
        candles[-1].open_time + timedelta(hours=1),
        Decimal("999999"),
    ).model_copy(update={"is_closed": False})

    base_rows = build_rows(
        candles,
        SYMBOL,
        Timeframe.H1,
        as_of_time=cutoff,
    )
    appended_rows = build_rows(
        [*candles, forming],
        SYMBOL,
        Timeframe.H1,
        as_of_time=cutoff,
    )
    base_result = train(
        candles,
        SYMBOL,
        Timeframe.H1,
        as_of_time=cutoff,
    )
    appended_result = train(
        [*candles, forming],
        SYMBOL,
        Timeframe.H1,
        as_of_time=cutoff,
    )

    assert appended_rows == base_rows
    assert appended_result.dataset_checksum == base_result.dataset_checksum
    assert appended_result.horizons == base_result.horizons
