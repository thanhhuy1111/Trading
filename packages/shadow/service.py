"""Phase 10: shadow mode - immutable proposal storage, outcome scheduling/evaluation, and
calibration aggregation. Never places a real order: outcome evaluation only ever reads
historical/point-in-time candles through an injected provider and writes a `ShadowOutcome`
record - there is no execution client import anywhere in this module."""

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from threading import RLock
from typing import Callable, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.domain.entities import ShadowOutcome, ShadowProposal
from packages.domain.enums import ShadowOutcomeStatus
from packages.market_data.models import Candle, Timeframe

CandlesProvider = Callable[[str, Timeframe, datetime, datetime], List[Candle]]
_TIMEFRAME_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


class ShadowStoreMode(str, Enum):
    RUNTIME = "RUNTIME"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class ShadowProposalTamperedError(Exception):
    """A `ShadowProposal` was submitted with a checksum that doesn't match its own content -
    either constructed incorrectly or mutated after the fact (the model is frozen, so this can
    only happen via a manually-crafted object, e.g. from an external caller)."""


class InMemoryShadowStore:
    """Offline, in-process storage - production wiring would drain this into a durable,
    append-only table the same way `packages.evidence.audit.EvidenceAuditLog` is designed to
    drain into `packages.audit.repository.AuditRepository`. One outcome per shadow proposal."""

    def __init__(self, mode: ShadowStoreMode = ShadowStoreMode.RUNTIME) -> None:
        self.mode = mode
        self._proposals: Dict[UUID, ShadowProposal] = {}
        self._outcomes: Dict[UUID, ShadowOutcome] = {}
        self._outcome_history: Dict[UUID, List[ShadowOutcome]] = {}
        self._evaluation_claims: set[UUID] = set()
        self._lock = RLock()

    def put_proposal(self, proposal: ShadowProposal) -> None:
        with self._lock:
            existing = self._proposals.get(proposal.shadow_id)
            if existing is not None:
                if existing != proposal:
                    raise ValueError("SHADOW_PROPOSAL_CONFLICT")
                return
            self._proposals[proposal.shadow_id] = proposal.model_copy(deep=True)

    def get_proposal(self, shadow_id: UUID) -> Optional[ShadowProposal]:
        with self._lock:
            proposal = self._proposals.get(shadow_id)
            return proposal.model_copy(deep=True) if proposal is not None else None

    def put_outcome(self, outcome: ShadowOutcome) -> None:
        with self._lock:
            existing = self._outcomes.get(outcome.shadow_id)
            if existing is not None:
                if existing == outcome:
                    return
                if existing.status != ShadowOutcomeStatus.PENDING:
                    raise ValueError("SHADOW_OUTCOME_ALREADY_FINAL")
                if outcome.evaluation_due_at != existing.evaluation_due_at:
                    raise ValueError("SHADOW_EVALUATION_DUE_CONFLICT")
            stored = outcome.model_copy(deep=True)
            self._outcomes[outcome.shadow_id] = stored
            self._outcome_history.setdefault(outcome.shadow_id, []).append(stored)

    def get_outcome(self, shadow_id: UUID) -> Optional[ShadowOutcome]:
        with self._lock:
            outcome = self._outcomes.get(shadow_id)
            return outcome.model_copy(deep=True) if outcome is not None else None

    def all_proposals(self) -> List[ShadowProposal]:
        with self._lock:
            return [proposal.model_copy(deep=True) for proposal in self._proposals.values()]

    def all_outcomes(self) -> List[ShadowOutcome]:
        with self._lock:
            return [outcome.model_copy(deep=True) for outcome in self._outcomes.values()]

    def outcome_history(self, shadow_id: UUID) -> List[ShadowOutcome]:
        with self._lock:
            return [
                outcome.model_copy(deep=True)
                for outcome in self._outcome_history.get(shadow_id, [])
            ]

    def claim_evaluation(self, shadow_id: UUID) -> bool:
        with self._lock:
            if shadow_id in self._evaluation_claims:
                return False
            current = self._outcomes.get(shadow_id)
            if current is None or current.status != ShadowOutcomeStatus.PENDING:
                return False
            self._evaluation_claims.add(shadow_id)
            return True

    def put_proposal_and_outcome(
        self,
        proposal: ShadowProposal,
        outcome: ShadowOutcome,
    ) -> None:
        with self._lock:
            if (
                proposal.shadow_id in self._proposals
                or outcome.shadow_id in self._outcomes
            ):
                existing_proposal = self._proposals.get(proposal.shadow_id)
                existing_outcome = self._outcomes.get(outcome.shadow_id)
                if (
                    existing_proposal == proposal
                    and existing_outcome is not None
                    and existing_outcome.evaluation_due_at
                    == outcome.evaluation_due_at
                ):
                    return
                raise ValueError("SHADOW_RECORD_EXISTS")
            stored_proposal = proposal.model_copy(deep=True)
            stored_outcome = outcome.model_copy(deep=True)
            self._proposals[proposal.shadow_id] = stored_proposal
            self._outcomes[outcome.shadow_id] = stored_outcome
            self._outcome_history[outcome.shadow_id] = [stored_outcome]

    def release_evaluation(self, shadow_id: UUID) -> None:
        with self._lock:
            self._evaluation_claims.discard(shadow_id)


class BaselineShadowService:
    def __init__(
        self,
        candles_provider: CandlesProvider,
        store: Optional[InMemoryShadowStore] = None,
        *,
        mode: ShadowStoreMode = ShadowStoreMode.RUNTIME,
    ) -> None:
        if store is not None and store.mode != mode:
            raise ValueError("SHADOW_STORE_MODE_MISMATCH")
        self._candles_provider = candles_provider
        self.store = store if store is not None else InMemoryShadowStore(mode)
        self._scheduler_enabled = True
        self._evaluation_lock = RLock()

    def set_scheduler_enabled(self, enabled: bool) -> None:
        self._scheduler_enabled = enabled

    def record_proposal(self, snapshot: ShadowProposal) -> ShadowProposal:
        recomputed = snapshot.compute_checksum()
        if snapshot.checksum and snapshot.checksum != recomputed:
            raise ShadowProposalTamperedError(
                f"ShadowProposal {snapshot.shadow_id} checksum mismatch: "
                f"stored={snapshot.checksum} recomputed={recomputed}"
            )
        final = snapshot if snapshot.checksum == recomputed else snapshot.model_copy(update={"checksum": recomputed})
        timeframe = Timeframe(str(final.candidate_snapshot["timeframe"]))
        horizon_bars = int(final.candidate_snapshot["prediction_horizon_bars"])
        if horizon_bars <= 0 or final.market_data_timestamp.tzinfo is None:
            raise ValueError("SHADOW_HORIZON_INVALID")
        due_at = final.market_data_timestamp + timedelta(
            seconds=_TIMEFRAME_SECONDS[timeframe] * horizon_bars
        )
        pending = ShadowOutcome(
            shadow_id=final.shadow_id,
            status=ShadowOutcomeStatus.PENDING,
            evaluation_due_at=due_at,
        )
        self.store.put_proposal_and_outcome(final, pending)
        return final

    def schedule_evaluation(self, shadow_id: UUID, due_at: datetime) -> ShadowOutcome:
        proposal = self.store.get_proposal(shadow_id)
        if proposal is None:
            raise ValueError("SHADOW_PROPOSAL_NOT_FOUND")
        if (
            due_at.tzinfo is None
            or proposal.market_data_timestamp.tzinfo is None
            or due_at <= proposal.market_data_timestamp
        ):
            raise ValueError("SHADOW_EVALUATION_TIME_INVALID")
        timeframe = Timeframe(str(proposal.candidate_snapshot["timeframe"]))
        horizon_bars = int(proposal.candidate_snapshot["prediction_horizon_bars"])
        canonical_due_at = proposal.market_data_timestamp + timedelta(
            seconds=_TIMEFRAME_SECONDS[timeframe] * horizon_bars
        )
        if due_at != canonical_due_at:
            raise ValueError("SHADOW_EVALUATION_HORIZON_MISMATCH")
        existing = self.store.get_outcome(shadow_id)
        if existing is not None:
            if existing.evaluation_due_at != due_at:
                raise ValueError("SHADOW_EVALUATION_DUE_CONFLICT")
            return existing
        outcome = ShadowOutcome(
            shadow_id=shadow_id, status=ShadowOutcomeStatus.PENDING, evaluation_due_at=due_at,
        )
        self.store.put_outcome(outcome)
        return outcome

    async def evaluate_due(self, as_of_time: datetime) -> List[ShadowOutcome]:
        if as_of_time.tzinfo is None:
            raise ValueError("SHADOW_AS_OF_INVALID")
        if not self._scheduler_enabled:
            return []
        with self._evaluation_lock:
            due = [
                o for o in self.store.all_outcomes()
                if o.status == ShadowOutcomeStatus.PENDING
                and o.evaluation_due_at <= as_of_time
            ]
            results = []
            for outcome in due:
                if not self.store.claim_evaluation(outcome.shadow_id):
                    continue
                try:
                    try:
                        evaluated = self._evaluate_one(outcome, as_of_time)
                    except Exception:  # noqa: BLE001
                        evaluated = outcome.model_copy(update={
                            "reason_codes": ["SHADOW_EVALUATION_RETRY_REQUIRED"],
                        })
                    self.store.put_outcome(evaluated)
                    if evaluated.status != ShadowOutcomeStatus.PENDING:
                        results.append(evaluated)
                finally:
                    self.store.release_evaluation(outcome.shadow_id)
            return results

    def _evaluate_one(self, outcome: ShadowOutcome, as_of_time: datetime) -> ShadowOutcome:
        proposal = self.store.get_proposal(outcome.shadow_id)
        if proposal is None:
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE, "evaluated_at": as_of_time,
                "reason_codes": ["SHADOW_PROPOSAL_NOT_FOUND"],
            })
        if proposal.checksum != proposal.compute_checksum():
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE,
                "evaluated_at": as_of_time,
                "reason_codes": ["SHADOW_PROPOSAL_CHECKSUM_INVALID"],
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

        if direction != "LONG":
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE,
                "evaluated_at": as_of_time,
                "reason_codes": ["SHADOW_DIRECTION_UNSUPPORTED"],
            })
        try:
            supplied_candles = self._candles_provider(
                symbol,
                timeframe,
                proposal.market_data_timestamp,
                outcome.evaluation_due_at,
            )
        except Exception:  # noqa: BLE001
            return outcome.model_copy(update={
                "reason_codes": ["SHADOW_CANDLE_PROVIDER_RETRY"],
            })
        candles = sorted(
            (
                candle
                for candle in supplied_candles
                if candle.symbol == symbol
                and candle.exchange == "binance"
                and candle.source == "binance_public"
                and candle.timeframe == timeframe
                and candle.is_closed
                and candle.exchange_timestamp <= candle.close_time
                and (
                    candle.close_time - candle.open_time
                ).total_seconds() == _TIMEFRAME_SECONDS[timeframe] - 1
                and proposal.market_data_timestamp
                < candle.close_time
                <= outcome.evaluation_due_at
            ),
            key=lambda candle: candle.close_time,
        )
        if len({candle.close_time for candle in candles}) != len(candles):
            return outcome.model_copy(update={
                "status": ShadowOutcomeStatus.DATA_UNAVAILABLE,
                "evaluated_at": as_of_time,
                "reason_codes": ["SHADOW_CANDLES_DUPLICATED"],
            })
        cadence_seconds = _TIMEFRAME_SECONDS[timeframe]
        horizon_bars = int(candidate["prediction_horizon_bars"])
        if (
            len(candles) != horizon_bars
            or (outcome.evaluation_due_at - candles[-1].close_time).total_seconds()
            not in (0, 1)
            or any(
                (right.close_time - left.close_time).total_seconds()
                != cadence_seconds
                for left, right in zip(candles, candles[1:], strict=False)
            )
        ):
            return outcome.model_copy(update={
                "reason_codes": ["SHADOW_CANDLE_WINDOW_INCOMPLETE"],
            })
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
        horizon_close = candles[-1].close_price
        threshold_raw = candidate.get("label_threshold_return")
        threshold_source = candidate.get("label_threshold_source")
        threshold_evidence = proposal.evidence_snapshot.get(threshold_source)
        actual_label = None
        prediction_correct = None
        if (
            candidate.get("label_version")
            == f"volatility_band_{horizon_bars}bar_v1"
            and threshold_raw is not None
            and isinstance(threshold_evidence, dict)
            and threshold_evidence.get("label_version")
            == candidate.get("label_version")
            and threshold_evidence.get("horizon_bars") == horizon_bars
            and Decimal(str(threshold_evidence.get("threshold_return")))
            == Decimal(str(threshold_raw))
        ):
            threshold = Decimal(str(threshold_raw))
            horizon_return = (horizon_close - entry_price) / entry_price
            actual_label = (
                "BULLISH"
                if horizon_return > threshold
                else "BEARISH"
                if horizon_return < -threshold
                else "NEUTRAL"
            )
            prediction_correct = actual_label == "BULLISH"

        return outcome.model_copy(update={
            "status": status,
            "evaluated_at": as_of_time,
            "actual_entry_reference": entry_price,
            "actual_exit_reference": exit_price,
            "gross_return_bps": gross_return_bps,
            "total_cost_bps": total_cost_bps,
            "net_return_bps": net_return_bps,
            "barrier_hit": barrier_hit,
            "horizon_close": horizon_close,
            "actual_label": actual_label,
            "prediction_correct": prediction_correct,
            "reason_codes": [f"EXIT_VIA_{status.value}"],
        })

    def performance_report(self, generated_at: datetime) -> "ShadowPerformanceReport":
        if generated_at.tzinfo is None:
            raise ValueError("SHADOW_REPORT_TIME_INVALID")
        proposals = tuple(
            proposal
            for proposal in self.store.all_proposals()
            if proposal.market_data_timestamp <= generated_at
        )
        outcomes_list: list[ShadowOutcome] = []
        for proposal in proposals:
            history = self.store.outcome_history(proposal.shadow_id)
            visible_final = tuple(
                outcome
                for outcome in history
                if outcome.evaluated_at is not None
                and outcome.evaluated_at <= generated_at
            )
            if visible_final:
                outcomes_list.append(visible_final[-1])
            elif history:
                outcomes_list.append(history[0])
        outcomes = tuple(outcomes_list)
        resolved = tuple(
            outcome
            for outcome in outcomes
            if outcome.status
            in (ShadowOutcomeStatus.BARRIER_EXIT, ShadowOutcomeStatus.TIMEOUT_EXIT)
            and outcome.net_return_bps is not None
        )
        labeled = tuple(
            outcome for outcome in resolved if outcome.prediction_correct is not None
        )
        correct = sum(outcome.prediction_correct is True for outcome in labeled)
        proposals_by_id = {proposal.shadow_id: proposal for proposal in proposals}
        agent_predictions_evaluated = 0
        agent_correct_predictions = 0
        agent_performance: Dict[str, Dict[str, int]] = {}
        for outcome in labeled:
            proposal = proposals_by_id.get(outcome.shadow_id)
            if proposal is None or outcome.actual_label is None:
                continue
            for assessment in proposal.agent_assessments_snapshot:
                direction = assessment.get("direction")
                if direction is not None:
                    key = (
                        f"{assessment.get('agent_name', 'unknown')}:"
                        f"{assessment.get('model_id') or assessment.get('model_version', 'unknown')}"
                    )
                    stats = agent_performance.setdefault(
                        key,
                        {"evaluated": 0, "correct": 0},
                    )
                    agent_predictions_evaluated += 1
                    stats["evaluated"] += 1
                    if str(direction) == outcome.actual_label:
                        agent_correct_predictions += 1
                        stats["correct"] += 1
        return ShadowPerformanceReport(
            generated_at=generated_at,
            proposals_recorded=len(proposals),
            outcomes_scheduled=len(outcomes),
            outcomes_evaluated=len(resolved),
            outcomes_unavailable=sum(
                outcome.status == ShadowOutcomeStatus.DATA_UNAVAILABLE
                for outcome in outcomes
            ),
            correct_predictions=correct,
            directional_accuracy=(
                Decimal(correct) / Decimal(len(labeled)) if labeled else None
            ),
            actual_bullish=sum(outcome.actual_label == "BULLISH" for outcome in labeled),
            actual_neutral=sum(outcome.actual_label == "NEUTRAL" for outcome in labeled),
            actual_bearish=sum(outcome.actual_label == "BEARISH" for outcome in labeled),
            agent_assessments_observed=sum(
                len(proposal.agent_assessments_snapshot) for proposal in proposals
            ),
            store_mode=self.store.mode,
            agent_predictions_evaluated=agent_predictions_evaluated,
            agent_correct_predictions=agent_correct_predictions,
            agent_performance=agent_performance,
        )


class ShadowPerformanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    proposals_recorded: int = Field(ge=0)
    outcomes_scheduled: int = Field(ge=0)
    outcomes_evaluated: int = Field(ge=0)
    outcomes_unavailable: int = Field(ge=0)
    correct_predictions: int = Field(ge=0)
    directional_accuracy: Optional[Decimal] = Field(default=None, ge=0, le=1)
    actual_bullish: int = Field(ge=0)
    actual_neutral: int = Field(ge=0)
    actual_bearish: int = Field(ge=0)
    agent_assessments_observed: int = Field(ge=0)
    store_mode: ShadowStoreMode
    agent_predictions_evaluated: int = Field(ge=0)
    agent_correct_predictions: int = Field(ge=0)
    agent_performance: Dict[str, Dict[str, int]]


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
        if outcome.prediction_correct is None:
            continue
        buckets.setdefault(bucket_key, []).append(outcome.prediction_correct)

    return {
        key: {
            "sample_count": Decimal(len(wins)),
            "realized_win_rate": Decimal(sum(wins)) / Decimal(len(wins)) if wins else Decimal("0"),
        }
        for key, wins in buckets.items()
    }
