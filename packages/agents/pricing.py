from decimal import Decimal
from typing import Dict, Optional

from packages.agents.models import SignalAction


def price_levels(
    ref: Optional[Decimal],
    is_long: bool,
    stop_pct: Decimal,
    take_profit_pct: Decimal,
    invalidation_pct: Decimal,
) -> Dict[str, Optional[Decimal]]:
    """Derive stop / take-profit / invalidation levels from a real market reference price.

    When no reference price is available the signal carries no price-derived
    levels (reference 0, levels None) so nothing downstream can fabricate a target.
    """
    if ref is None:
        return {"reference": Decimal("0"), "stop": None, "take_profit": None, "invalidation": None}

    if is_long:
        stop = ref * (Decimal("1") - stop_pct)
        take_profit = ref * (Decimal("1") + take_profit_pct)
        invalidation = ref * (Decimal("1") - invalidation_pct)
    else:
        stop = ref * (Decimal("1") + stop_pct)
        take_profit = ref * (Decimal("1") - take_profit_pct)
        invalidation = ref * (Decimal("1") + invalidation_pct)

    return {"reference": ref, "stop": stop, "take_profit": take_profit, "invalidation": invalidation}


def expected_return_bps(
    ref: Optional[Decimal],
    action: SignalAction,
    take_profit: Optional[Decimal],
    confidence: Decimal,
) -> Optional[Decimal]:
    """Confidence-weighted expected return proxy derived from the agent's own target.

    NOTE: this is a transparent placeholder proxy (target distance x confidence),
    NOT a calibrated forecast. When the reference price or target is unavailable it
    returns None so the Meta Allocator produces NO_TRADE instead of inventing edge.
    """
    if ref is None or take_profit is None or action not in (SignalAction.LONG, SignalAction.SHORT):
        return None
    target_return = abs(take_profit - ref) / ref
    return target_return * Decimal("10000") * confidence
