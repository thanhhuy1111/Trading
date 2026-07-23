"""Phase 7: Recommendation Runtime — every one of the 11 `ApplicationResultState` values must
be reachable, and the orchestrator must never fabricate a proposal or silently swallow an
unexpected error."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from packages.agents.strategy_config import default_strategy_config
from packages.domain.enums import ApplicationResultState, MetaLabelDecision, ModelType
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.market_data.models import Candle, Timeframe
from packages.ports.interfaces import PortfolioSnapshot, RecommendationRequest
from packages.risk.portfolio_governor import BaselinePortfolioRiskGovernor
from packages.runtime.recommendation_service import (
    BaselineRecommendationService,
    RecommendationServiceConfig,
)

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTC/USDT"


def _rising_candles(n: int = 120, start_price: Decimal = Decimal("50000")) -> List[Candle]:
    candles = []
    price = start_price
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        step = price * Decimal("0.01")
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step
    return candles


_ALL_CANDLES = _rising_candles(120)


def _candles_provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
    if symbol != SYMBOL:
        return []
    return [c for c in _ALL_CANDLES if start <= c.close_time <= end]


def _empty_candles_provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
    return []


def _request(as_of: datetime, symbols: Optional[List[str]] = None) -> RecommendationRequest:
    return RecommendationRequest(
        request_id=uuid4(), symbols=symbols or [SYMBOL], timeframe=Timeframe.H1, as_of_time=as_of,
        generated_at=as_of,
    )


def _evidence_key_for_default_candidate() -> EvidenceKey:
    """Mirrors exactly what BaselineRecommendationService._analyze_one_unsafe builds for the
    default PassThroughMetaLabelService + default strategy config, so a test can pre-register
    an evidence record the runtime will actually look up (exact-match, no fallback)."""
    return EvidenceKey(
        strategy_name="checkpoint2_pipeline_demo", strategy_version="1.0.0", symbol=SYMBOL, timeframe="1h",
        model_type=ModelType.PASS_THROUGH.value, model_version="n/a", feature_version="standard_v1",
        label_version="meta_label_v1", dataset_checksum="n/a", gate_version="gate_v1",
        config_hash=default_strategy_config.config_hash, code_commit="n/a",
    )


def _record(status: EvidenceStatus) -> EvidenceRecord:
    return EvidenceRecord(
        key=_evidence_key_for_default_candidate(), status=status, generated_at=T0, total_oos_trades=50,
    )


async def test_no_candles_yields_no_candidate() -> None:
    service = BaselineRecommendationService(candles_provider=_empty_candles_provider)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.NO_CANDIDATE.value
    assert result.proposals == []


async def test_too_few_candles_data_quality_or_no_candidate() -> None:
    def provider(symbol, timeframe, start, end):
        return [c for c in _ALL_CANDLES[:5] if start <= c.close_time <= end]

    service = BaselineRecommendationService(candles_provider=provider)
    result = await service.analyze(_request(_ALL_CANDLES[4].close_time), SYMBOL)
    assert result.application_result_state in (
        ApplicationResultState.NO_CANDIDATE.value, ApplicationResultState.DATA_QUALITY_FAILED.value,
    )
    assert result.proposals == []


async def test_stale_data_state() -> None:
    as_of = _ALL_CANDLES[-1].close_time
    config = RecommendationServiceConfig(staleness_threshold=timedelta(hours=6))
    service = BaselineRecommendationService(candles_provider=_candles_provider, config=config)
    request = _request(as_of)
    stale_request = RecommendationRequest(
        request_id=request.request_id, symbols=request.symbols, timeframe=request.timeframe,
        as_of_time=as_of, generated_at=as_of + timedelta(days=10),
    )
    result = await service.analyze(stale_request, SYMBOL)
    assert result.application_result_state == ApplicationResultState.STALE_DATA.value
    assert result.proposals == []


async def test_default_config_produces_research_proposal_with_no_evidence_registered() -> None:
    """The default, permissive path: shadow mode must always have something to evaluate, even
    with an empty evidence registry."""
    evidence_service = EvidenceStore()
    service = BaselineRecommendationService(candles_provider=_candles_provider, evidence_service=evidence_service)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.RESEARCH_PROPOSAL.value
    assert len(result.proposals) == 1
    assert result.proposals[0].approved_risk_pct is None
    assert result.proposals[0].application_result_state == ApplicationResultState.RESEARCH_PROPOSAL


async def test_require_actionable_evidence_blocks_with_insufficient_evidence() -> None:
    evidence_service = EvidenceStore()
    config = RecommendationServiceConfig(require_actionable_evidence=True)
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_service, config=config,
    )
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.INSUFFICIENT_EVIDENCE.value
    assert result.proposals == []


async def test_rejected_evidence_status_is_strategy_not_approved() -> None:
    evidence_service = EvidenceStore()
    evidence_service.register(_record(EvidenceStatus.REJECTED))
    service = BaselineRecommendationService(candles_provider=_candles_provider, evidence_service=evidence_service)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.STRATEGY_NOT_APPROVED.value
    assert result.proposals == []


async def test_approved_evidence_with_healthy_portfolio_yields_approved_proposal() -> None:
    evidence_service = EvidenceStore()
    evidence_service.register(_record(EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    portfolio_snapshot = PortfolioSnapshot(
        available=True, nav=Decimal("100000"), open_risk_pct=Decimal("0"), open_position_count=0,
        daily_realized_pnl_pct=Decimal("0"), weekly_realized_pnl_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0"), kill_switch_active=False, positions_by_symbol={},
    )
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_service,
        portfolio_snapshot_provider=lambda: portfolio_snapshot,
    )
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.APPROVED_PROPOSAL.value
    assert len(result.proposals) == 1
    assert result.proposals[0].approved_risk_pct is not None
    assert result.proposals[0].approved_risk_pct > Decimal("0")


async def test_approved_evidence_but_portfolio_state_unavailable_is_system_degraded() -> None:
    evidence_service = EvidenceStore()
    evidence_service.register(_record(EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    service = BaselineRecommendationService(candles_provider=_candles_provider, evidence_service=evidence_service)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.SYSTEM_DEGRADED.value
    assert result.proposals == []


async def test_approved_evidence_but_max_positions_reached_is_risk_limit_exceeded() -> None:
    evidence_service = EvidenceStore()
    evidence_service.register(_record(EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    portfolio_snapshot = PortfolioSnapshot(
        available=True, nav=Decimal("100000"), open_risk_pct=Decimal("0"), open_position_count=5,
        daily_realized_pnl_pct=Decimal("0"), weekly_realized_pnl_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0"), kill_switch_active=False, positions_by_symbol={},
    )
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_service,
        portfolio_snapshot_provider=lambda: portfolio_snapshot,
        portfolio_risk_governor=BaselinePortfolioRiskGovernor(),
    )
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.RISK_LIMIT_EXCEEDED.value
    assert result.proposals == []


class _RejectingMetaLabelService:
    async def predict(self, candidate):
        from packages.domain.entities import ModelPrediction
        return ModelPrediction(
            candidate_id=candidate.candidate_id, model_type=ModelType.PASS_THROUGH, model_version="n/a",
            feature_version="standard_v1", label_version="meta_label_v1", probability=None,
            decision=MetaLabelDecision.REJECT, reason_codes=["TEST_FORCED_REJECT"], status="BASELINE_ONLY",
        )


async def test_meta_label_reject_yields_no_trade() -> None:
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, meta_label_service=_RejectingMetaLabelService(),
    )
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.NO_TRADE.value
    assert result.proposals == []


async def test_require_trained_model_with_pass_through_is_model_not_available() -> None:
    config = RecommendationServiceConfig(require_trained_model=True)
    service = BaselineRecommendationService(candles_provider=_candles_provider, config=config)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.MODEL_NOT_AVAILABLE.value
    assert result.proposals == []


class _ExplodingMetaLabelService:
    async def predict(self, candidate):
        raise RuntimeError("simulated unexpected failure")


async def test_unexpected_exception_is_surfaced_as_system_degraded_not_swallowed() -> None:
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, meta_label_service=_ExplodingMetaLabelService(),
    )
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    assert result.application_result_state == ApplicationResultState.SYSTEM_DEGRADED.value
    assert any("simulated unexpected failure" in code for code in result.reason_codes)


async def test_scan_aggregates_across_symbols_and_never_raises_on_missing_data() -> None:
    def provider(symbol, timeframe, start, end):
        if symbol == "ETH/USDT":
            return []  # no data at all for this symbol
        return _candles_provider(symbol, timeframe, start, end)

    service = BaselineRecommendationService(candles_provider=provider)
    result = await service.scan(_request(_ALL_CANDLES[-1].close_time, symbols=[SYMBOL, "ETH/USDT"]))
    assert result.application_result_state == ApplicationResultState.RESEARCH_PROPOSAL.value
    assert len(result.proposals) == 1
    assert any("ETH/USDT:NO_MARKET_DATA_AVAILABLE" in code for code in result.reason_codes)


async def test_readiness_status_never_conflates_axes() -> None:
    evidence_service = EvidenceStore()
    service = BaselineRecommendationService(candles_provider=_candles_provider, evidence_service=evidence_service)
    result = await service.analyze(_request(_ALL_CANDLES[-1].close_time), SYMBOL)
    readiness = result.readiness_status
    assert readiness.architecture_readiness.value == "READY"
    assert readiness.live_readiness.value == "DISABLED"
    # Strategy/evidence readiness must reflect "no approved evidence yet", never APPROVED,
    # even though architecture and shadow readiness are both fully operational.
    assert readiness.strategy_readiness.value != "UNIVERSAL_APPROVED"
    assert readiness.strategy_readiness.value != "ASSET_SPECIFIC_APPROVED"
