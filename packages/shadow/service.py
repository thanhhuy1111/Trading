"""Phase 10: shadow mode - immutable proposal storage, outcome scheduling/evaluation, and
calibration aggregation. Never places a real order: outcome evaluation only ever reads
historical/point-in-time candles through an injected provider and writes a `ShadowOutcome`
record - there is no execution client import anywhere in this module."""

from datetime import datetime
from decimal import Decimal
from typing import Callable, Dict, List, Optional
from uuid import UUID

from packages.domain.entities import ShadowOutcome, ShadowProposal
from packages.domain.enums import ShadowOutcomeStatus
from packages.market_data.models import Candle, Timeframe

CandlesProvider = Callable[[str, Timeframe, datetime, datetime], List[Candle]]


class ShadowProposalTamperedError(Exception):
    """A `ShadowProposal` was submitted with a checksum that doesn't match its own content -
    either constructed incorrectly or mutated after the fact (the model is frozen, so this can
    only happen via a manually-crafted object, e.g. from an external caller)."""


class InMemoryShadowStore:
    """Offline, in-process storage - production wiring would drain this into a durable,
    append-only table the same way `packages.evidence.audit.EvidenceAuditLog` is designed to
    drain into `packages.audit.repository.AuditRepository`. One outcome per shadow proposal."""

    def __init__(self) -> None:
        self._proposals: Dict[UUID, ShadowProposal] = {}
        self._outcomes: Dict[UUID, ShadowOutcome] = {}

    def put_proposal(self, proposal: ShadowProposal) -> None:
        self._proposals[proposal.shadow_id] = proposal

    def get_proposal(self, shadow_id: UUID) -> Optional[ShadowProposal]:
        return self._proposals.get(shadow_id)

    def put_outcome(self, outcome: ShadowOutcome) -> None:
        self._outcomes[outcome.shadow_id] = outcome

    def get_outcome(self, shadow_id: UUID) -> Optional[ShadowOutcome]:
        return self._outcomes.get(shadow_id)

    def all_proposals(self) -> List[ShadowProposal]:
        return list(self._proposals.values())

    def all_outcomes(self) -> List[ShadowOutcome]:
        return list(self._outcomes.values())


class BaselineShadowService:
    def __init__(self, candles_provider: CandlesProvider, store: Optional[InMemoryShadowStore] = None) -> None:
        self._candles_provider = candles_provider
        self.store = store if store is not None else InMemoryShadowStore()

    def record_proposal(self, snapshot: ShadowProposal) -> ShadowProposal:
        recomputed = snapshot.compute_checksum()
        if snapshot.checksum and snapshot.checksum != recomputed:
            raise ShadowProposalTamperedError(
                f"ShadowProposal {snapshot.shadow_id} checksum mismatch: "
                f"stored={snapshot.checksum} recomputed={recomputed}"
            )
        final = snapshot if snapshot.checksum == recomputed else snapshot.model_copy(update={"checksum": recomputed})
        self.store.put_proposal(final)
        return final

    def schedule_evaluation(self, shadow_id: UUID, due_at: datetime) -> ShadowOutcome:
        outcome = ShadowOutcome(
            shadow_id=shadow_id, status=ShadowOutcomeStatus.PENDING, evaluation_due_at=due_at,
        )
        self.store.put_outcome(outcome)
        return outcome

    async def evaluate_due(self, as_of_time: datetime) -> List[ShadowOutcome]:
        due = [
            o for o in self.store.all_outcomes()
            if o.status == ShadowOutcomeStatus.PENDING and o.evaluation_due_at <= as_of_time
        ]
        results = []
        for outcome in due:
            evaluated = self._evaluate_one(outcome, as_of_time)
            self.store.put_outcome(evaluated)
            results.append(evaluated)
        return results

    def _evaluate_one(self, outcome: ShadowOutcome, as_of_time: datetime) -> ShadowOutcome:
        proposal = self.store.get_proposal(outcome.shadow_id)
        if proposal is None:
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE, "evaluated_at": as_of_time,
                "reason_codes": ["SHADOW_PROPOSAL_NOT_FOUND"],
            })

        candidate = proposal.candidate_snapshot
        symbol = candidate.get("symbol")
        timeframe_str = candidate.get("timeframe")
        direction = candidate.get("direction")
        entry_reference = candidate.get("entry_reference")
        if not symbol or not timeframe_str or not direction or entry_reference is None:
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE, "evaluated_at": as_of_time,
                "reason_codes": ["CANDIDATE_SNAPSHOT_INCOMPLETE"],
            })
        assert isinstance(symbol, str) and isinstance(timeframe_str, str) and isinstance(direction, str)

        timeframe = Timeframe(timeframe_str)
        entry_price = Decimal(str(entry_reference))
        stop_loss = Decimal(str(candidate["stop_loss"])) if candidate.get("stop_loss") is not None else None
        take_profit = Decimal(str(candidate["take_profit"])) if candidate.get("take_profit") is not None else None

        candles = self._candles_provider(symbol, timeframe, proposal.market_data_timestamp, outcome.evaluation_due_at)
        candles = [c for c in candles if c.close_time > proposal.market_data_timestamp]
        if not candles:
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE, "evaluated_at": as_of_time,
                "reason_codes": ["NO_CANDLES_FOR_EVALUATION_WINDOW"],
            })

        exit_price, barrier_hit = _first_barrier_hit(candles, direction, entry_price, stop_loss, take_profit)
        status = ShadowOutcomeStatus.BARRIER_EXIT if barrier_hit is not None else ShadowOutcomeStatus.TIMEOUT_EXIT
        if exit_price is None:
            exit_price = candles[-1].close_price  # no barrier reached - mark-to-last-close at timeout

        gross_return_bps = _gross_return_bps(direction, entry_price, exit_price)
        total_cost_bps = _round_trip_cost_bps(candidate)
        net_return_bps = gross_return_bps - total_cost_bps

        return outcome.model_copy(update={
            "status": status,
            "evaluated_at": as_of_time,
            "actual_entry_reference": entry_price,
            "actual_exit_reference": exit_price,
            "gross_return_bps": gross_return_bps,
            "total_cost_bps": total_cost_bps,
            "net_return_bps": net_return_bps,
            "barrier_hit": barrier_hit,
            "reason_codes": [f"EXIT_VIA_{status.value}"],
        })


def _first_barrier_hit(
    candles: List[Candle], direction: str, entry_price: Decimal,
    stop_loss: Optional[Decimal], take_profit: Optional[Decimal],
) -> "tuple[Optional[Decimal], Optional[str]]":
    """LONG-only (Section 4: spot-only MVP, no short direction supported anywhere in this
    architecture). UPPER = take_profit, LOWER = stop_loss; scans candles in order and returns
    the first bar whose high/low crosses either level. Neither set -> (None, None), the caller
    marks TIMEOUT_EXIT at the last available close."""
    if direction != "LONG":
        return None, None
    for candle in candles:
        if stop_loss is not None and candle.low_price <= stop_loss:
            return stop_loss, "LOWER"
        if take_profit is not None and candle.high_price >= take_profit:
            return take_profit, "UPPER"
    return None, None


def _gross_return_bps(direction: str, entry_price: Decimal, exit_price: Decimal) -> Decimal:
    if entry_price == 0:
        return Decimal("0")
    raw = (exit_price - entry_price) / entry_price
    if direction != "LONG":
        raw = -raw  # documented for completeness; this architecture only ever proposes LONG
    return raw * Decimal("10000")


def _round_trip_cost_bps(candidate: Dict[str, object]) -> Decimal:
    """Entry + exit each pay fee/spread/slippage once - a documented simplification (this is a
    baseline cost model, not a claim about realized execution cost; Section 2: "do not optimize
    toward profitable backtest results in this task")."""
    fee = Decimal(str(candidate.get("estimated_fee_bps") or "0"))
    spread = Decimal(str(candidate.get("estimated_spread_bps") or "0"))
    slippage = Decimal(str(candidate.get("estimated_slippage_bps") or "0"))
    return (fee + spread + slippage) * Decimal("2")


def aggregate_calibration(
    proposals: List[ShadowProposal],
    outcomes_by_shadow_id: Dict[UUID, ShadowOutcome],
    bucket_width: Decimal = Decimal("0.1"),
) -> Dict[str, Dict[str, Decimal]]:
    """Buckets resolved shadow outcomes by the proposal's `calibrated_probability` (read from
    `candidate_snapshot`) into `bucket_width`-wide deciles and reports the realized win rate
    (net_return_bps > 0) per bucket - the basic calibration-curve input Phase 11/12 monitoring
    and retraining evidence review consume. Unresolved (PENDING/DATA_UNAVAILABLE) outcomes and
    proposals with no calibrated_probability are excluded, never treated as a 0% or 100% win."""
    buckets: Dict[str, List[bool]] = {}
    for proposal in proposals:
        outcome = outcomes_by_shadow_id.get(proposal.shadow_id)
        resolved_statuses = (ShadowOutcomeStatus.BARRIER_EXIT, ShadowOutcomeStatus.TIMEOUT_EXIT)
        if outcome is None or outcome.status not in resolved_statuses:
            continue
        probability = proposal.candidate_snapshot.get("calibrated_probability")
        if probability is None or outcome.net_return_bps is None:
            continue
        bucket_index = int(Decimal(str(probability)) / bucket_width)
        bucket_key = f"{bucket_index * bucket_width}-{(bucket_index + 1) * bucket_width}"
        buckets.setdefault(bucket_key, []).append(outcome.net_return_bps > 0)

    return {
        key: {
            "sample_count": Decimal(len(wins)),
            "realized_win_rate": Decimal(sum(wins)) / Decimal(len(wins)) if wins else Decimal("0"),
        }
        for key, wins in buckets.items()
    }
