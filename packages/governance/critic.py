from datetime import datetime
from decimal import Decimal
from typing import List

from packages.agents.models import AgentSignal, MarketRegime, SignalAction
from packages.governance.cost_estimator import cost_estimator
from packages.governance.models import (
    CriticComponentResult,
    CriticDecision,
    CriticSeverity,
)


class CriticAgent:
    """Deterministic, Rule-Based Critic Agent for signal scrutiny and governance."""

    def review_signal(self, signal: AgentSignal, current_time: datetime) -> CriticDecision:
        components: List[CriticComponentResult] = []
        risk_flags: List[str] = []
        warning_codes: List[str] = []
        rejection_codes: List[str] = []

        orig_conf = signal.confidence
        total_penalty = Decimal("0.0")

        # 1. Data Quality & Freshness Critic
        if signal.expires_at <= current_time:
            rejection_codes.append("SIGNAL_EXPIRED")
            components.append(CriticComponentResult(
                critic_name="FreshnessCritic",
                passed=False,
                severity=CriticSeverity.CRITICAL,
                confidence_penalty=Decimal("1.0"),
                reason_codes=["SIGNAL_EXPIRED"],
                explanation=["Signal expiration time has passed."],
                evaluated_at=current_time
            ))

        # 2. Regime Compatibility Critic
        if signal.market_regime in [MarketRegime.LIQUIDITY_RISK, MarketRegime.UNKNOWN]:
            rejection_codes.append("REGIME_UNHEALTHY")
            components.append(CriticComponentResult(
                critic_name="RegimeCompatibilityCritic",
                passed=False,
                severity=CriticSeverity.CRITICAL,
                confidence_penalty=Decimal("1.0"),
                reason_codes=["REGIME_UNHEALTHY"],
                explanation=[f"Market regime {signal.market_regime.value} is unsafe for trading."],
                evaluated_at=current_time
            ))

        # 3. Cost & Edge Feasibility Critic
        cost = cost_estimator.estimate_cost(signal.symbol)
        # HONEST DEFAULT: a missing expected return is treated as 0 bps (never a fabricated
        # positive edge). Downstream this yields NO_TRADE rather than inventing an opportunity.
        if signal.expected_return_bps is None:
            expected_bps = Decimal("0.0")
            warning_codes.append("EXPECTED_RETURN_UNAVAILABLE")
        else:
            expected_bps = signal.expected_return_bps

        if expected_bps <= cost.total_cost_bps:
            warning_codes.append("INSUFFICIENT_EXPECTED_EDGE")
            total_penalty += Decimal("0.15")
            components.append(CriticComponentResult(
                critic_name="CostCritic",
                passed=False,
                severity=CriticSeverity.WARNING,
                confidence_penalty=Decimal("0.15"),
                reason_codes=["EXPECTED_EDGE_LOW"],
                explanation=[f"Expected return {expected_bps} bps <= estimated costs {cost.total_cost_bps} bps."],
                evaluated_at=current_time
            ))

        # 4. Uncertainty Penalty
        if signal.confidence < Decimal("0.60"):
            total_penalty += Decimal("0.05")
            warning_codes.append("WEAK_ORIGINAL_CONFIDENCE")

        # Calculate adjusted confidence (strictly <= original_confidence)
        adjusted_conf = max(Decimal("0.0"), orig_conf - total_penalty)

        approved = (
            (len(rejection_codes) == 0)
            and (adjusted_conf >= Decimal("0.40"))
            and (signal.action != SignalAction.NO_SIGNAL)
        )

        return CriticDecision(
            signal_id=signal.signal_id,
            agent_id=signal.agent_id,
            approved_for_aggregation=approved,
            original_confidence=orig_conf,
            adjusted_confidence=adjusted_conf,
            confidence_penalty=total_penalty,
            estimated_cost_bps=cost.total_cost_bps,
            risk_flags=risk_flags,
            warning_codes=warning_codes,
            rejection_codes=rejection_codes,
            review_components=components,
            reviewed_at=current_time,
            valid_until=signal.expires_at,
            critic_version="1.0.0",
            policy_version="1.0.0"
        )


critic_agent = CriticAgent()
