"""Phase 10: shadow mode - immutable snapshot storage, outcome scheduling/evaluation
(barrier/timeout), and calibration aggregation. Never places a real order."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List
from uuid import uuid4

from packages.domain.entities import TradeProposal
from packages.domain.enums import ApplicationResultState, ShadowOutcomeStatus, ShadowProposalKind
from packages.market_data.models import Candle, Timeframe
from packages.shadow.builder import build_shadow_proposal, shadow_kind_for_application_result_state
from packages.shadow.service import (
    BaselineShadowService,
    InMemoryShadowStore,
    ShadowProposalTamperedError,
    ShadowStoreMode,
    aggregate_calibration,
)

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTC/USDT"


def _proposal(
    state: ApplicationResultState = ApplicationResultState.RESEARCH_PROPOSAL,
    stop_loss=None, take_profit=None, calibrated_probability=None,
) -> TradeProposal:
    return TradeProposal(
        candidate_id=uuid4(), symbol=SYMBOL, timeframe="1h", direction="LONG",
        entry_reference=Decimal("50000"), stop_loss=stop_loss, take_profit=take_profit,
        estimated_fee_bps=Decimal("10"), estimated_spread_bps=Decimal("2"), estimated_slippage_bps=Decimal("5"),
        calibrated_probability=calibrated_probability, strategy_version="1.0.0", model_version="n/a",
        evidence_status="RESEARCH_ONLY", proposal_expiry=T0 + timedelta(hours=1),
        application_result_state=state,
    )


def _build(proposal: TradeProposal):
    return build_shadow_proposal(
        proposal,
        market_data_timestamp=T0,
        prediction_horizon_bars=5,
        label_version="volatility_band_5bar_v1",
        label_threshold_return=Decimal("0.00001"),
        label_threshold_source="synthetic_contract_fixture",
        evidence_snapshot={
            "synthetic_contract_fixture": {
                "label_version": "volatility_band_5bar_v1",
                "horizon_bars": 5,
                "threshold_return": "0.00001",
            }
        },
    )


def _candle(i: int, close: Decimal, high=None, low=None) -> Candle:
    ct = T0 + timedelta(hours=i)
    return Candle(
        exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
        close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1, open_price=close,
        high_price=high if high is not None else close + Decimal("5"),
        low_price=low if low is not None else close - Decimal("5"),
        close_price=close, volume=Decimal("10"), is_closed=True,
    )


def test_shadow_kind_maps_research_and_approved_only() -> None:
    assert shadow_kind_for_application_result_state(
        ApplicationResultState.RESEARCH_PROPOSAL,
    ) == ShadowProposalKind.RESEARCH_SHADOW
    assert shadow_kind_for_application_result_state(
        ApplicationResultState.APPROVED_PROPOSAL,
    ) == ShadowProposalKind.APPROVED_SHADOW
    assert shadow_kind_for_application_result_state(ApplicationResultState.NO_TRADE) is None


def test_build_shadow_proposal_computes_checksum_and_kind() -> None:
    proposal = _proposal()
    shadow = _build(proposal)
    assert shadow.kind == ShadowProposalKind.RESEARCH_SHADOW
    assert shadow.checksum == shadow.compute_checksum()
    assert shadow.candidate_snapshot["symbol"] == SYMBOL


def test_build_shadow_proposal_rejects_non_proposal_states() -> None:
    proposal = _proposal(state=ApplicationResultState.NO_TRADE)
    try:
        _build(proposal)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_record_proposal_is_immutable_and_tamper_detected() -> None:
    service = BaselineShadowService(candles_provider=lambda *a: [])
    shadow = _build(_proposal())
    stored = service.record_proposal(shadow)
    assert stored.checksum == shadow.checksum
    assert service.record_proposal(shadow) == stored

    tampered = shadow.model_copy(update={"candidate_snapshot": {**shadow.candidate_snapshot, "symbol": "ETH/USDT"}})
    try:
        service.record_proposal(tampered)
        raise AssertionError("expected ShadowProposalTamperedError")
    except ShadowProposalTamperedError:
        pass


async def test_barrier_exit_hits_take_profit() -> None:
    def provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
        return [
            _candle(i, Decimal("50000") + i * 100, high=Decimal("50000") + i * 100 + Decimal("200"))
            for i in range(5)
        ]

    service = BaselineShadowService(candles_provider=provider)
    proposal = _proposal(take_profit=Decimal("50250"))
    shadow = service.record_proposal(_build(proposal))
    service.schedule_evaluation(shadow.shadow_id, due_at=T0 + timedelta(hours=5))

    outcomes = await service.evaluate_due(T0 + timedelta(hours=10))
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == ShadowOutcomeStatus.BARRIER_EXIT
    assert outcome.barrier_hit == "UPPER"
    assert outcome.actual_exit_reference == Decimal("50250")
    assert outcome.gross_return_bps is not None and outcome.gross_return_bps > 0
    assert outcome.net_return_bps == outcome.gross_return_bps - outcome.total_cost_bps


async def test_timeout_exit_when_no_barrier_configured() -> None:
    def provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
        return [_candle(i, Decimal("50000") + i * 10) for i in range(5)]

    service = BaselineShadowService(candles_provider=provider)
    proposal = _proposal()  # no stop_loss/take_profit
    shadow = service.record_proposal(_build(proposal))
    service.schedule_evaluation(shadow.shadow_id, due_at=T0 + timedelta(hours=5))

    outcomes = await service.evaluate_due(T0 + timedelta(hours=10))
    outcome = outcomes[0]
    assert outcome.status == ShadowOutcomeStatus.TIMEOUT_EXIT
    assert outcome.barrier_hit is None


async def test_no_candles_remains_retryable_without_fabricated_outcome() -> None:
    service = BaselineShadowService(candles_provider=lambda *a: [])
    shadow = service.record_proposal(_build(_proposal()))
    service.schedule_evaluation(shadow.shadow_id, due_at=T0 + timedelta(hours=5))

    outcomes = await service.evaluate_due(T0 + timedelta(hours=10))
    assert outcomes == []
    outcome = service.store.get_outcome(shadow.shadow_id)
    assert outcome.status == ShadowOutcomeStatus.PENDING
    assert outcome.reason_codes == ["SHADOW_CANDLE_WINDOW_INCOMPLETE"]
    assert outcome.net_return_bps is None


async def test_pending_outcome_not_yet_due_is_not_evaluated() -> None:
    service = BaselineShadowService(candles_provider=lambda *a: [_candle(0, Decimal("50000"))])
    shadow = service.record_proposal(_build(_proposal()))

    outcomes = await service.evaluate_due(T0 + timedelta(hours=1))
    assert outcomes == []
    assert service.store.get_outcome(shadow.shadow_id).status == ShadowOutcomeStatus.PENDING


async def test_scheduler_kill_switch_idempotency_and_future_candles() -> None:
    def provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
        return [
            *[_candle(i, Decimal("50000") + i * 10) for i in range(5)],
            _candle(20, Decimal("60000")),
        ]

    service = BaselineShadowService(candles_provider=provider)
    shadow = service.record_proposal(
        _build(_proposal())
    )
    due_at = T0 + timedelta(hours=5)
    scheduled = service.schedule_evaluation(shadow.shadow_id, due_at)
    assert service.schedule_evaluation(shadow.shadow_id, due_at) == scheduled
    service.set_scheduler_enabled(False)
    assert await service.evaluate_due(T0 + timedelta(hours=10)) == []
    assert service.store.get_outcome(shadow.shadow_id).status == ShadowOutcomeStatus.PENDING
    service.set_scheduler_enabled(True)
    evaluated = await service.evaluate_due(T0 + timedelta(hours=10))
    assert evaluated[0].actual_exit_reference != Decimal("60000")
    assert await service.evaluate_due(T0 + timedelta(hours=10)) == []
    report = service.performance_report(T0 + timedelta(hours=10))
    assert report.outcomes_evaluated == 1
    assert report.directional_accuracy is not None


async def test_incomplete_window_rejects_and_provider_failure_retries() -> None:
    calls = 0

    def provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        if calls == 2:
            return [_candle(0, Decimal("50000"))]
        return [_candle(i, Decimal("50000") + i) for i in range(5)]

    service = BaselineShadowService(candles_provider=provider)
    shadow = service.record_proposal(
        _build(_proposal())
    )
    assert await service.evaluate_due(T0 + timedelta(hours=10)) == []
    assert service.store.get_outcome(shadow.shadow_id).status == ShadowOutcomeStatus.PENDING
    assert await service.evaluate_due(T0 + timedelta(hours=10)) == []
    assert service.store.get_outcome(shadow.shadow_id).status == ShadowOutcomeStatus.PENDING
    resolved = await service.evaluate_due(T0 + timedelta(hours=10))
    assert resolved[0].actual_label == "BULLISH"
    assert resolved[0].prediction_correct is True
    serialized = resolved[0].model_dump(mode="json")
    assert serialized["actual_label"] == "BULLISH"
    assert serialized["prediction_correct"] is True
    assert len(service.store.outcome_history(shadow.shadow_id)) == 4
    historical_report = service.performance_report(T0 + timedelta(hours=5))
    assert historical_report.outcomes_scheduled == 1
    assert historical_report.outcomes_evaluated == 0


def test_runtime_and_replay_stores_cannot_be_mixed() -> None:
    replay_store = InMemoryShadowStore(ShadowStoreMode.HISTORICAL_REPLAY)
    try:
        BaselineShadowService(
            candles_provider=lambda *args: [],
            store=replay_store,
            mode=ShadowStoreMode.RUNTIME,
        )
        raise AssertionError("expected mode mismatch")
    except ValueError as exc:
        assert str(exc) == "SHADOW_STORE_MODE_MISMATCH"


async def test_calibration_aggregation_excludes_unresolved_and_missing_probability() -> None:
    def provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
        return [_candle(i, Decimal("50000") + i * 50) for i in range(5)]  # steady rise -> wins

    service = BaselineShadowService(candles_provider=provider)
    proposal_with_prob = _proposal(calibrated_probability=Decimal("0.65"))
    proposal_without_prob = _proposal(calibrated_probability=None)

    shadow_a = service.record_proposal(_build(proposal_with_prob))
    shadow_b = service.record_proposal(_build(proposal_without_prob))
    service.schedule_evaluation(shadow_a.shadow_id, due_at=T0 + timedelta(hours=5))
    service.schedule_evaluation(shadow_b.shadow_id, due_at=T0 + timedelta(hours=5))
    await service.evaluate_due(T0 + timedelta(hours=10))

    outcomes_by_id = {o.shadow_id: o for o in service.store.all_outcomes()}
    calibration = aggregate_calibration(service.store.all_proposals(), outcomes_by_id)
    assert sum(int(b["sample_count"]) for b in calibration.values()) == 1  # only shadow_a has a probability
