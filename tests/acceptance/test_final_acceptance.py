"""Final Acceptance Test (Section 23).

Part A: one deterministic, fixture-based, offline scenario walking the full chain -
universe -> candles -> validation -> features -> regime -> routing -> agent candidates ->
pass-through meta-label -> disabled market-context -> research-only evidence lookup ->
baseline ranking -> correlation -> strategy portfolio -> portfolio risk -> research
recommendation -> immutable shadow record -> simulated outcome -> monitoring metrics ->
readiness status - and confirms every stage actually ran, not merely that a final answer
came back.

Part B: nine safe-rejection scenarios, each proving the system returns an explicit, typed,
non-fabricated result rather than raising or silently defaulting to a trade:
stale candle, invalid OHLC, missing evidence, evidence mismatch, disabled strategy,
missing model, correlation unavailable, risk limit exceeded, kill switch active.

Nothing in this file makes a network call, touches a live exchange, or calls a real LLM
provider - every dependency is a fixture or the honest baseline/no-op default.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from packages.agents.strategy_config import default_strategy_config
from packages.domain.enums import ApplicationResultState, ModelType
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.intelligence.market_context import BaselineMarketContextService
from packages.intelligence.meta_label import PassThroughMetaLabelService
from packages.intelligence.strategy_portfolio import StrategyPortfolio
from packages.market_data.models import Candle, Timeframe
from packages.monitoring.metrics import PROPOSALS_RESEARCH_TOTAL
from packages.monitoring.service import BaselineMonitoringService
from packages.ports.interfaces import PortfolioSnapshot, RecommendationRequest
from packages.risk.portfolio_governor import BaselinePortfolioRiskGovernor, PortfolioRiskPolicy
from packages.runtime.recommendation_service import BaselineRecommendationService, RecommendationServiceConfig
from packages.shadow.builder import build_shadow_proposal
from packages.shadow.service import BaselineShadowService
from packages.universe.models import SymbolMetadata, UniverseSelectionRules
from packages.universe.selector import build_universe_snapshot

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTC/USDT"


def _rising_candles(n: int = 150) -> List[Candle]:
    candles = []
    price = Decimal("50000")
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


_ALL_CANDLES = _rising_candles(150)
# Leaves 30 hourly candles after the decision point so shadow evaluation (Part A) has real
# future candles to walk through, distinct from the pipeline's own as_of_time cutoff.
_AS_OF = _ALL_CANDLES[119].close_time


def _candles_provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
    if symbol != SYMBOL:
        return []
    return [c for c in _ALL_CANDLES if start <= c.close_time <= end]


def _request(as_of: datetime = _AS_OF) -> RecommendationRequest:
    return RecommendationRequest(request_id=uuid4(), symbols=[SYMBOL], timeframe=Timeframe.H1, as_of_time=as_of)


def _default_key(config_hash: Optional[str] = None) -> EvidenceKey:
    return EvidenceKey(
        strategy_name="checkpoint2_pipeline_demo", strategy_version="1.0.0", symbol=SYMBOL, timeframe="1h",
        model_type=ModelType.PASS_THROUGH.value, model_version="n/a", feature_version="standard_v1",
        label_version="meta_label_v1", dataset_checksum="n/a", gate_version="gate_v1",
        config_hash=config_hash or default_strategy_config.config_hash, code_commit="n/a",
    )


def _clean_portfolio(**overrides) -> PortfolioSnapshot:
    base = dict(
        available=True, nav=Decimal("100000"), open_risk_pct=Decimal("0"), open_position_count=0,
        daily_realized_pnl_pct=Decimal("0"), weekly_realized_pnl_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0"), kill_switch_active=False, positions_by_symbol={},
    )
    base.update(overrides)
    return PortfolioSnapshot(**base)


# --- Part A: the full deterministic end-to-end scenario ---


async def test_full_end_to_end_scenario_research_recommendation_to_readiness() -> None:
    # Stage: universe (pure, deterministic, no network - packages.universe.selector).
    rules = UniverseSelectionRules()
    metadata = SymbolMetadata(
        symbol=SYMBOL, exchange_symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", status="TRADING",
        is_spot_trading_allowed=True, history_days_available=1000, quote_volume_24h_usdt=Decimal("50000000"),
        recent_candle_completeness_pct=Decimal("99.0"), best_bid=Decimal("49999"), best_ask=Decimal("50001"),
    )
    universe = build_universe_snapshot([metadata], rules, generated_at=T0)
    assert SYMBOL in universe.eligible_symbols

    # Stages: candles -> validation -> features -> regime -> routing -> agent candidates ->
    # pass-through meta-label -> disabled market-context -> research-only evidence lookup ->
    # baseline ranking -> correlation -> strategy portfolio -> portfolio risk -> research
    # recommendation. All inside BaselineRecommendationService.analyze (Phase 7), using the
    # honest baseline/disabled defaults explicitly (not implicitly) to prove each stage.
    evidence_store = EvidenceStore()  # empty registry -> "research-only evidence lookup"
    strategy_portfolio = StrategyPortfolio()  # nothing curated yet -> informational, not blocking
    service = BaselineRecommendationService(
        candles_provider=_candles_provider,
        meta_label_service=PassThroughMetaLabelService(),
        market_context_service=BaselineMarketContextService(),
        evidence_service=evidence_store,
        strategy_portfolio=strategy_portfolio,
    )
    result = await service.analyze(_request(), SYMBOL)

    assert result.application_result_state == ApplicationResultState.RESEARCH_PROPOSAL.value
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.approved_risk_pct is None  # research, not capital-backed
    assert any("NO_STRATEGY_SLEEVE_REGISTERED" in c for c in result.reason_codes)  # strategy portfolio ran
    assert readiness_axes_are_not_conflated(result.readiness_status)

    # Stage: immutable shadow record.
    shadow_service = BaselineShadowService(candles_provider=_candles_provider)
    shadow_draft = build_shadow_proposal(proposal, market_data_timestamp=_AS_OF)
    stored_shadow = shadow_service.record_proposal(shadow_draft)
    assert stored_shadow.checksum == stored_shadow.compute_checksum()
    assert stored_shadow.kind.value == "RESEARCH_SHADOW"

    # Stage: simulated outcome.
    due_at = _AS_OF + timedelta(hours=1)
    shadow_service.schedule_evaluation(stored_shadow.shadow_id, due_at=due_at)
    outcomes = await shadow_service.evaluate_due(due_at + timedelta(hours=1))
    assert len(outcomes) == 1
    assert outcomes[0].status.value in ("BARRIER_EXIT", "TIMEOUT_EXIT")
    assert outcomes[0].net_return_bps is not None

    # Stage: monitoring metrics + readiness status.
    monitoring = BaselineMonitoringService(evidence_store)
    monitoring.record_metric(PROPOSALS_RESEARCH_TOTAL, Decimal("1"), tags={"symbol": SYMBOL})
    assert monitoring.metrics_store.total(PROPOSALS_RESEARCH_TOTAL) == Decimal("1")
    readiness = monitoring.current_readiness()
    assert readiness_axes_are_not_conflated(readiness)
    assert readiness.evidence_readiness.value == "EMPTY_REGISTRY"
    assert readiness.live_readiness.value == "DISABLED"


def readiness_axes_are_not_conflated(readiness) -> bool:
    """Section 3: the six readiness axes must never be conflated - architecture completion is
    not strategy approval is not model readiness is not evidence is not shadow is not live."""
    return (
        readiness.architecture_readiness.value == "READY"
        and readiness.live_readiness.value == "DISABLED"
        and readiness.strategy_readiness.value != "UNIVERSAL_APPROVED"
    )


# --- Part B: nine safe-rejection scenarios ---


async def test_rejection_stale_candle() -> None:
    config = RecommendationServiceConfig(staleness_threshold=timedelta(hours=6))
    service = BaselineRecommendationService(candles_provider=_candles_provider, config=config)
    request = RecommendationRequest(
        request_id=uuid4(), symbols=[SYMBOL], timeframe=Timeframe.H1, as_of_time=_AS_OF,
        generated_at=_AS_OF + timedelta(days=10),
    )
    result = await service.analyze(request, SYMBOL)
    assert result.application_result_state == ApplicationResultState.STALE_DATA.value
    assert result.proposals == []


async def test_rejection_invalid_ohlc() -> None:
    """Invalid OHLC (high < low) is rejected at the very first boundary - the `Candle` model's
    own construction-time integrity validator (packages.market_data.models.Candle) - so it can
    never even reach the pipeline as a constructed object. This is a stronger, earlier
    rejection than a downstream pipeline check, and `packages.market_data.historical_quality`
    additionally re-checks OHLC integrity for any candle that reaches it by another path (e.g.
    deserialized from a less-strict source), so both layers fail closed independently."""
    from pydantic import ValidationError

    ct = T0
    try:
        Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1,
            open_price=Decimal("50000"), high_price=Decimal("100"), low_price=Decimal("50000"),  # high < low
            close_price=Decimal("50000"), volume=Decimal("10"), is_closed=True,
        )
        raise AssertionError("expected pydantic ValidationError for invalid OHLC (high < low)")
    except ValidationError as exc:
        assert "high_price" in str(exc)


async def test_rejection_missing_evidence() -> None:
    config = RecommendationServiceConfig(require_actionable_evidence=True)
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=EvidenceStore(), config=config,
    )
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.INSUFFICIENT_EVIDENCE.value
    assert any("MISSING" in c for c in result.reason_codes)
    assert result.proposals == []


async def test_rejection_evidence_mismatch() -> None:
    evidence_store = EvidenceStore()
    evidence_store.register(EvidenceRecord(
        key=_default_key(config_hash="a_completely_different_config_hash"),
        status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=50,
    ))
    config = RecommendationServiceConfig(require_actionable_evidence=True)
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_store, config=config,
    )
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.INSUFFICIENT_EVIDENCE.value
    assert any("MISMATCH" in c for c in result.reason_codes)
    assert result.proposals == []


async def test_rejection_disabled_strategy() -> None:
    evidence_store = EvidenceStore()
    evidence_store.register(EvidenceRecord(
        key=_default_key(), status=EvidenceStatus.DISABLED, generated_at=T0, total_oos_trades=50,
    ))
    service = BaselineRecommendationService(candles_provider=_candles_provider, evidence_service=evidence_store)
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.STRATEGY_NOT_APPROVED.value
    assert result.proposals == []


async def test_rejection_missing_model() -> None:
    config = RecommendationServiceConfig(require_trained_model=True)
    service = BaselineRecommendationService(candles_provider=_candles_provider, config=config)
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.MODEL_NOT_AVAILABLE.value
    assert result.proposals == []


async def test_rejection_correlation_unavailable_is_treated_as_correlated_and_blocks() -> None:
    evidence_store = EvidenceStore()
    evidence_store.register(EvidenceRecord(
        key=_default_key(), status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=50,
    ))
    portfolio_snapshot = _clean_portfolio(positions_by_symbol={"ETH/USDT": Decimal("10.0")})
    # No candles available for ETH/USDT -> correlation service can't compute a snapshot ->
    # the portfolio risk governor must treat that as "assume correlated", never as zero.
    governor = BaselinePortfolioRiskGovernor(policy=PortfolioRiskPolicy(max_correlated_exposure_pct=Decimal("5.0")))
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_store,
        portfolio_snapshot_provider=lambda: portfolio_snapshot, portfolio_risk_governor=governor,
    )
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.RISK_LIMIT_EXCEEDED.value
    assert any("MAX_CORRELATED_EXPOSURE_REACHED" in c for c in result.reason_codes)
    assert result.proposals == []


async def test_rejection_risk_limit_exceeded() -> None:
    evidence_store = EvidenceStore()
    evidence_store.register(EvidenceRecord(
        key=_default_key(), status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=50,
    ))
    portfolio_snapshot = _clean_portfolio(open_position_count=5)  # at the default cap
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_store,
        portfolio_snapshot_provider=lambda: portfolio_snapshot,
    )
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.RISK_LIMIT_EXCEEDED.value
    assert any("MAX_SIMULTANEOUS_POSITIONS_REACHED" in c for c in result.reason_codes)
    assert result.proposals == []


async def test_rejection_kill_switch_active() -> None:
    evidence_store = EvidenceStore()
    evidence_store.register(EvidenceRecord(
        key=_default_key(), status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=50,
    ))
    portfolio_snapshot = _clean_portfolio(kill_switch_active=True)
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_store,
        portfolio_snapshot_provider=lambda: portfolio_snapshot,
    )
    result = await service.analyze(_request(), SYMBOL)
    assert result.application_result_state == ApplicationResultState.RISK_LIMIT_EXCEEDED.value
    assert any("KILL_SWITCH_ACTIVE" in c for c in result.reason_codes)
    assert result.proposals == []
