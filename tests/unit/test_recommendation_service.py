"""Integration-style tests for packages/recommendation/service.py.

No network calls: `_UptrendMarketDataProvider` below reuses the exact synthetic-candle
pattern from tests/unit/test_decision_pipeline_e2e.py (steady +0.5%/bar, proven to
produce a real TREND_UP regime and a real BUY TradeIntent), anchored so the last candle
closes near "now" so freshness gates pass. `MockMarketDataProvider` (the repo's existing
test double) is used for the no-trade / market-overview paths, where its monotonic
straight-line series is fine since we don't need a trade to be produced.

Exercises the real pipeline end to end: candles -> FeaturePipeline -> DecisionService
(real agents/critic/consensus/allocator) -> PredictionService -> EvidenceService ->
proposal gates -> ranker. Each test builds its own isolated ModelRegistry/EvidenceRegistry
so it never depends on -- or pollutes -- the process-wide singletons.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator, List, Sequence

import pytest

from packages.market_data.adapters.mock import MockMarketDataProvider
from packages.market_data.models import (
    Candle,
    CandleUpdate,
    ExchangeInfo,
    MarketTrade,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
    SymbolInfo,
    Timeframe,
)
from packages.market_data.symbol_registry import symbol_registry
from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
from packages.prediction.meta_label_model import ThresholdMetaLabelModel
from packages.prediction.registry import ModelArtifact, ModelRegistry
from packages.prediction.return_model import LinearRegressionWeights, LinearReturnModel
from packages.prediction.service import PredictionService
from packages.prediction.volatility_model import RealizedVolatilityModel
from packages.recommendation.config import RecommendationConfig
from packages.recommendation.evidence_service import EvidenceRegistry, EvidenceService
from packages.recommendation.models import EvidenceStatus, MarketStatus, RecommendationStatus, StrategyEvidence
from packages.recommendation.proposal_store import ProposalStore
from packages.recommendation.proposal_validator import validate_proposal
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION, RecommendationService


def _uptrend_candles_ending_now(n: int = 40, start: Decimal = Decimal("50000.00")) -> List[Candle]:
    """Same shape as tests/unit/test_decision_pipeline_e2e.py::_uptrend_candles, but
    anchored to end at (approximately) the current wall-clock time so freshness gates pass.
    """
    end = datetime.now(timezone.utc)
    t0 = end - timedelta(hours=n)
    candles = []
    price = start
    for i in range(n):
        c_time = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        open_p = price
        close_p = price + step
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTCUSDT",
                exchange_timestamp=c_time,
                open_time=c_time,
                close_time=c_time + timedelta(minutes=59),
                timeframe=Timeframe.H1,
                open_price=open_p,
                high_price=close_p + Decimal("10"),
                low_price=open_p - Decimal("10"),
                close_price=close_p,
                volume=Decimal("100.00"),
                trades_count=1000,
                is_closed=True,
            )
        )
        price = close_p
    return candles


class _UptrendMarketDataProvider:
    """Minimal MarketDataProvider stub: ignores the requested window and always returns
    the same proven uptrend series ending near now. Structurally satisfies the
    MarketDataProvider protocol (duck typing) for exactly the methods RecommendationService
    calls.
    """

    def __init__(self) -> None:
        self._candles = _uptrend_candles_ending_now()

    async def get_exchange_info(self) -> ExchangeInfo:
        return ExchangeInfo(exchange_id="test", name="Test Exchange", is_active=True)

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = symbol_registry.get_symbol_info(symbol)
        if not info:
            raise ValueError(f"unknown symbol {symbol}")
        return info

    async def fetch_candles(self, symbol, timeframe, start_time, end_time, limit=500) -> Sequence[Candle]:
        return self._candles

    async def fetch_order_book_snapshot(self, symbol: str, depth: int = 100) -> OrderBookSnapshot:
        last = self._candles[-1].close_price
        return OrderBookSnapshot(
            exchange="test",
            symbol=symbol,
            sequence_id=1,
            bids=[OrderBookLevel(price=last - Decimal("1.00"), quantity=Decimal("5.0"))],
            asks=[OrderBookLevel(price=last + Decimal("1.00"), quantity=Decimal("5.0"))],
            exchange_timestamp=datetime.now(timezone.utc),
        )

    async def stream_trades(self, symbols: Sequence[str]) -> AsyncIterator[MarketTrade]:
        return
        yield  # pragma: no cover

    async def stream_candles(self, symbols, timeframes) -> AsyncIterator[CandleUpdate]:
        return
        yield  # pragma: no cover

    async def stream_order_book(self, symbols: Sequence[str]) -> AsyncIterator[OrderBookDelta]:
        return
        yield  # pragma: no cover


def _empty_service(provider=None) -> RecommendationService:
    """Service wired exactly like production defaults: no trained model, no evidence."""
    return RecommendationService(
        market_data_provider=provider or MockMarketDataProvider(),
        prediction_svc=PredictionService(registry=ModelRegistry()),
        evidence_svc=EvidenceService(registry=EvidenceRegistry()),
        store=ProposalStore(),
    )


def _service_with_approved_strategy() -> RecommendationService:
    prediction_registry = ModelRegistry()
    up_weights = LogisticRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], up_coefficients=[500.0], up_intercept=0.5,
        down_coefficients=[-500.0], down_intercept=-1.0,
    )
    artifact = ModelArtifact(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        model_version="logreg_v1",
        feature_version="standard_v1",
        direction_model=LogisticRegressionDirectionModel(up_weights),
        return_model=LinearReturnModel(
            LinearRegressionWeights(
                model_version="v1", feature_names=["ema_20_slope"], coefficients=[1000.0], intercept=20.0
            )
        ),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(min_return_to_volatility_ratio=Decimal("0.001")),
        calibration_score=Decimal("0.80"),
    )
    prediction_registry.register(artifact)

    evidence_registry = EvidenceRegistry()
    evidence_registry.register(
        StrategyEvidence(
            strategy_name=PIPELINE_STRATEGY_NAME,
            strategy_version=PIPELINE_STRATEGY_VERSION,
            model_version="logreg_v1",
            feature_version="standard_v1",
            config_hash="any",
            status=EvidenceStatus.INSUFFICIENT,  # re-derived by evaluate_approval, not trusted as-is
            out_of_sample_trades=250,
            profit_factor=Decimal("1.35"),
            sharpe=Decimal("1.10"),
            maximum_drawdown_pct=Decimal("6.0"),
            expectancy_bps=Decimal("12.0"),
            walk_forward_windows=4,
            created_at=datetime.now(timezone.utc),
        )
    )

    return RecommendationService(
        market_data_provider=_UptrendMarketDataProvider(),
        prediction_svc=PredictionService(registry=prediction_registry),
        evidence_svc=EvidenceService(registry=evidence_registry, config=RecommendationConfig()),
        store=ProposalStore(),
    )


@pytest.mark.asyncio
async def test_scan_never_fabricates_proposals_when_nothing_is_registered():
    """Default shipped state: no trained model, no evidence -> never PROPOSALS_AVAILABLE."""
    service = _empty_service()
    result = await service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"])

    assert result.status != RecommendationStatus.PROPOSALS_AVAILABLE
    assert result.proposals == []
    assert "BTCUSDT" in result.symbols_evaluated


@pytest.mark.asyncio
async def test_scan_produces_proposals_when_strategy_is_approved_and_calibrated():
    service = _service_with_approved_strategy()
    result = await service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"], max_results=3)

    assert result.status == RecommendationStatus.PROPOSALS_AVAILABLE
    assert len(result.proposals) >= 1
    proposal = result.proposals[0]
    assert proposal.symbol == "BTCUSDT"
    assert proposal.side == "BUY"
    assert proposal.probability_profit is not None
    assert proposal.evidence_id is not None
    assert proposal.decision_lineage.trade_intent_id is not None


@pytest.mark.asyncio
async def test_scan_respects_max_results():
    service = _service_with_approved_strategy()
    result = await service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"], max_results=1)
    assert len(result.proposals) <= 1


@pytest.mark.asyncio
async def test_proposal_from_scan_is_retrievable_and_valid_from_store():
    service = _service_with_approved_strategy()
    store = service._store  # noqa: SLF001 - white-box check that the scan actually persisted it
    result = await service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"])

    assert result.proposals, "expected at least one proposal for this fixture"
    proposal = result.proposals[0]
    stored = store.get(proposal.proposal_id)
    assert stored is not None
    assert stored.proposal_id == proposal.proposal_id

    validation = validate_proposal(stored, now=proposal.generated_at + timedelta(seconds=10))
    assert validation.valid is True


@pytest.mark.asyncio
async def test_get_market_overview_returns_real_regime_and_price():
    service = _empty_service()
    overview = await service.get_market_overview(symbols=["BTCUSDT"], timeframes=["1h"])

    assert overview.overall_market_status in (MarketStatus.NORMAL, MarketStatus.STALE)
    assert len(overview.symbols) == 1
    symbol_overview = overview.symbols[0]
    assert symbol_overview.symbol == "BTCUSDT"
    assert symbol_overview.last_price is not None
    assert len(symbol_overview.timeframes) == 1
    assert symbol_overview.timeframes[0].market_regime  # populated, not fabricated by the LLM


@pytest.mark.asyncio
async def test_get_market_overview_marks_unavailable_for_unsupported_timeframe():
    service = _empty_service()
    overview = await service.get_market_overview(symbols=["BTCUSDT"], timeframes=["3m"])
    assert overview.symbols[0].market_status == MarketStatus.UNAVAILABLE
