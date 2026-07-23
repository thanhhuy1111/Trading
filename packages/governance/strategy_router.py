"""Deterministic, versioned regime -> strategy routing.

Maps a detected MarketRegime to the set of agent StrategyTypes allowed to contribute a signal
for that decision. This is a hard filter applied BEFORE DecisionService runs its agents (see
DecisionService.decide's `allowed_strategy_types` parameter) — an agent whose StrategyType
isn't in the routed set for the current regime simply never runs for that bar, rather than
running and being discarded after the fact.

Known gap, stated plainly rather than faked: the platform has no Pullback agent implemented
yet (only Trend, Mean Reversion, Breakout — packages/agents/{trend,reversion,breakout}.py).
The Master Plan's example routing table mentions "Trend + Pullback" for TREND_UP; this router
routes TREND_UP/TREND_DOWN to {TREND_FOLLOWING} only, because routing to a StrategyType with
no agent behind it would silently do nothing while looking like a real routing decision.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

from packages.agents.models import MarketRegime, StrategyType

ROUTER_VERSION = "router_v1"


@dataclass(frozen=True)
class RoutingDecision:
    regime: MarketRegime
    allowed_strategy_types: FrozenSet[StrategyType]
    is_no_trade: bool
    reason_codes: List[str]
    router_version: str = ROUTER_VERSION


# regime -> (allowed strategy types, reason codes). An empty set means NO_TRADE for this
# regime regardless of what any agent would otherwise say.
_ROUTING_TABLE: Dict[MarketRegime, Tuple[FrozenSet[StrategyType], List[str]]] = {
    MarketRegime.TREND_UP: (
        frozenset({StrategyType.TREND_FOLLOWING}),
        ["REGIME_TREND_UP", "PULLBACK_STRATEGY_NOT_IMPLEMENTED"],
    ),
    MarketRegime.TREND_DOWN: (
        # Spot long-only MVP already rejects SHORT at the allocator (packages/governance/
        # allocator.py Gate 2), so routing TREND_FOLLOWING here has no executable effect today
        # — kept routed rather than forced to NO_TRADE so the router's own decision is honest
        # about which regime it saw, independent of the allocator's separate spot-only policy.
        frozenset({StrategyType.TREND_FOLLOWING}),
        ["REGIME_TREND_DOWN", "SPOT_LONG_ONLY_LIMITS_EXECUTION"],
    ),
    MarketRegime.SIDEWAYS: (
        frozenset({StrategyType.MEAN_REVERSION}),
        ["REGIME_SIDEWAYS"],
    ),
    MarketRegime.HIGH_VOLATILITY: (
        frozenset({StrategyType.BREAKOUT}),
        ["REGIME_HIGH_VOLATILITY"],
    ),
    MarketRegime.LOW_VOLATILITY: (
        # Tight ranges favor mean reversion over trend/breakout continuation.
        frozenset({StrategyType.MEAN_REVERSION}),
        ["REGIME_LOW_VOLATILITY"],
    ),
    MarketRegime.LIQUIDITY_RISK: (
        frozenset(),
        ["REGIME_LOW_LIQUIDITY_NO_TRADE"],
    ),
    MarketRegime.TRANSITION: (
        frozenset(),
        ["REGIME_TRANSITION_UNCERTAIN_NO_TRADE"],
    ),
    MarketRegime.UNKNOWN: (
        frozenset(),
        ["REGIME_UNKNOWN_NO_TRADE"],
    ),
}


def route(regime: MarketRegime) -> RoutingDecision:
    allowed, reasons = _ROUTING_TABLE[regime]
    return RoutingDecision(
        regime=regime,
        allowed_strategy_types=allowed,
        is_no_trade=(len(allowed) == 0),
        reason_codes=list(reasons),
    )
