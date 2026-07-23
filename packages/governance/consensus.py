from datetime import datetime
from decimal import Decimal
from typing import List, Tuple
from uuid import uuid4

from packages.agents.models import AgentSignal, SignalAction
from packages.governance.models import (
    ConsensusDirection,
    ConsensusResult,
    CriticDecision,
)
from packages.market_data.models import Timeframe


class SignalConsensusEngine:
    """Consensus Engine aggregating Critic Decisions into consensus direction and weighted confidence."""

    def evaluate_consensus(
        self,
        symbol: str,
        decisions_and_signals: List[Tuple[CriticDecision, AgentSignal]],
        current_time: datetime
    ) -> ConsensusResult:
        if not decisions_and_signals:
            return ConsensusResult(
                consensus_id=uuid4(),
                symbol=symbol,
                timeframe_scope=[Timeframe.M15],
                direction=ConsensusDirection.INSUFFICIENT_EVIDENCE,
                agreement_score=Decimal("0.0"),
                disagreement_score=Decimal("0.0"),
                participating_signals=[],
                accepted_signals=[],
                rejected_signals=[],
                weighted_confidence=Decimal("0.0"),
                weighted_expected_return_bps=Decimal("0.0"),
                reason_codes=["NO_SIGNALS_PROVIDED"],
                generated_at=current_time
            )

        participating_ids = [s.signal_id for _, s in decisions_and_signals]
        accepted = [(d, s) for d, s in decisions_and_signals if d.approved_for_aggregation]
        rejected_ids = [s.signal_id for d, s in decisions_and_signals if not d.approved_for_aggregation]
        accepted_ids = [s.signal_id for _, s in accepted]

        if not accepted:
            return ConsensusResult(
                consensus_id=uuid4(),
                symbol=symbol,
                timeframe_scope=[Timeframe.M15],
                direction=ConsensusDirection.INSUFFICIENT_EVIDENCE,
                agreement_score=Decimal("0.0"),
                disagreement_score=Decimal("0.0"),
                participating_signals=participating_ids,
                accepted_signals=[],
                rejected_signals=rejected_ids,
                weighted_confidence=Decimal("0.0"),
                weighted_expected_return_bps=Decimal("0.0"),
                reason_codes=["ALL_SIGNALS_REJECTED_BY_CRITIC"],
                generated_at=current_time
            )

        long_votes = sum((d.adjusted_confidence for d, s in accepted if s.action == SignalAction.LONG), Decimal("0.0"))
        short_votes = sum(
            (d.adjusted_confidence for d, s in accepted if s.action == SignalAction.SHORT), Decimal("0.0")
        )
        total_votes = sum((d.adjusted_confidence for d, s in accepted), Decimal("0.0"))

        if total_votes == Decimal("0.0"):
            weighted_conf = Decimal("0.0")
            agree_score = Decimal("0.0")
            disagree_score = Decimal("0.0")
        else:
            weighted_conf = total_votes / Decimal(len(accepted))
            agree_score = max(long_votes, short_votes) / total_votes
            disagree_score = min(long_votes, short_votes) / total_votes

        # Direction determination
        reasons = []
        is_conflicted = (
            long_votes > Decimal("0")
            and short_votes > Decimal("0")
            and (min(long_votes, short_votes) / total_votes > Decimal("0.30"))
        )
        if is_conflicted:
            direction = ConsensusDirection.CONFLICTED
            reasons.append("LONG_SHORT_CONFLICT_DETECTED")
        elif long_votes > short_votes and long_votes > Decimal("0"):
            direction = ConsensusDirection.LONG
            reasons.append("BULLISH_CONSENSUS_ACHIEVED")
        elif short_votes > long_votes and short_votes > Decimal("0"):
            direction = ConsensusDirection.SHORT
            reasons.append("BEARISH_CONSENSUS_ACHIEVED")
        else:
            direction = ConsensusDirection.FLAT
            reasons.append("FLAT_CONSENSUS")

        # Weighted expected return calculation
        expected_returns = []
        for d, s in accepted:
            # HONEST DEFAULT: missing expected return contributes 0 bps (no fabricated edge).
            ret_bps = s.expected_return_bps if s.expected_return_bps is not None else Decimal("0.0")
            expected_returns.append(ret_bps * d.adjusted_confidence)

        weighted_ret = (
            (sum(expected_returns, Decimal("0.0")) / total_votes) if total_votes > Decimal("0") else Decimal("0.0")
        )

        return ConsensusResult(
            consensus_id=uuid4(),
            symbol=symbol,
            timeframe_scope=[Timeframe.M15],
            direction=direction,
            agreement_score=agree_score,
            disagreement_score=disagree_score,
            participating_signals=participating_ids,
            accepted_signals=accepted_ids,
            rejected_signals=rejected_ids,
            weighted_confidence=weighted_conf,
            weighted_expected_return_bps=weighted_ret,
            reason_codes=reasons,
            generated_at=current_time
        )


signal_consensus_engine = SignalConsensusEngine()
