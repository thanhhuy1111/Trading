from decimal import Decimal

from pydantic import BaseModel

from packages.agents.models import AgentSignal, SignalAction


class SignalOutcome(BaseModel):
    signal_id: str
    agent_id: str
    action: SignalAction
    reference_price: Decimal
    outcome_price: Decimal
    forward_return_bps: Decimal
    is_directionally_correct: bool


class AgentEvaluationReport(BaseModel):
    agent_id: str
    total_signals: int
    long_signals: int
    short_signals: int
    no_signals: int
    directional_accuracy: Decimal
    avg_forward_return_bps: Decimal


class SignalEvaluator:
    """Evaluates historical signals post-horizon to calculate accuracy and forward returns."""

    def evaluate_signal(self, signal: AgentSignal, actual_future_price: Decimal) -> SignalOutcome:
        ref_p = signal.reference_price
        ret = (actual_future_price - ref_p) / ref_p if ref_p > 0 else Decimal("0")
        forward_bps = ret * Decimal("10000")

        is_correct = False
        if signal.action == SignalAction.LONG and forward_bps > Decimal("0"):
            is_correct = True
        elif signal.action == SignalAction.SHORT and forward_bps < Decimal("0"):
            is_correct = True
        elif signal.action in [SignalAction.FLAT, SignalAction.NO_SIGNAL]:
            is_correct = True

        return SignalOutcome(
            signal_id=str(signal.signal_id),
            agent_id=signal.agent_id,
            action=signal.action,
            reference_price=ref_p,
            outcome_price=actual_future_price,
            forward_return_bps=forward_bps,
            is_directionally_correct=is_correct
        )


signal_evaluator = SignalEvaluator()
