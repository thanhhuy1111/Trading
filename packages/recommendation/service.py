"""RecommendationService: the only place market data becomes a TradeProposal.

Wires the REAL, already-remediated pipeline:

    Market Data (public) -> FeaturePipeline -> DecisionService (agents -> critic ->
    consensus -> allocator) -> PredictionService -> EvidenceService -> cost -> gates ->
    ProposalBuilder -> OpportunityRanker -> RecommendationResult

It never calls ExecutionEngine, never touches a private exchange adapter, and never
computes a final order quantity. The Gemini chat agent only ever calls this service
through the typed tool functions in packages/chat_agent/tool_registry.py -- it cannot
import or reach any of the objects below.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.agents.strategy_config import StrategyConfig, default_strategy_config
from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.governance.decision_service import DecisionResult, DecisionService, decision_service
from packages.market_data.adapters.base import MarketDataProvider
from packages.market_data.adapters.factory import MarketDataProviderFactory
from packages.market_data.models import Candle, OrderBookSnapshot, Timeframe
from packages.prediction.service import PredictionService, prediction_service
from packages.recommendation.config import RecommendationConfig, recommendation_config
from packages.recommendation.evidence_service import EvidenceService, evidence_service
from packages.recommendation.exceptions import MarketDataUnavailableError
from packages.recommendation.models import (
    DecisionLineage,
    MarketOverview,
    MarketStatus,
    RecommendationResult,
    RecommendationStatus,
    StrategyEvidence,
    SymbolMarketOverview,
    TimeframeSnapshot,
    TradeCandidate,
)
from packages.recommendation.opportunity_ranker import opportunity_ranker
from packages.recommendation.proposal_builder import proposal_builder
from packages.recommendation.proposal_store import ProposalStore, proposal_store
from packages.recommendation.proposal_validator import check_candidate_gates
from packages.recommendation.timeframes import max_allowed_staleness_seconds

# The whole agent -> critic -> consensus -> allocator chain is evaluated as a single
# strategy identity for evidence-approval purposes (it is one deterministic pipeline, not
# independently-tradeable sub-strategies). Bump the version when the pipeline's decision
# logic changes in a way that would invalidate previously-recorded evidence.
PIPELINE_STRATEGY_NAME = "multi_agent_consensus_pipeline"
PIPELINE_STRATEGY_VERSION = "1.0.0"

_TIMEFRAME_MINUTES: Dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}


def _parse_timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError as exc:
        raise MarketDataUnavailableError(f"Unsupported timeframe '{value}'") from exc


def _volatility_bucket(vol_20: Optional[Decimal], strategy_config: StrategyConfig) -> str:
    if vol_20 is None:
        return "UNKNOWN"
    if vol_20 >= strategy_config.regime_high_vol_threshold:
        return "HIGH"
    if vol_20 >= strategy_config.regime_high_vol_threshold / Decimal("2"):
        return "MEDIUM"
    return "LOW"


def _liquidity_facts(order_book: Optional[OrderBookSnapshot], config: RecommendationConfig) -> Tuple[Decimal, Decimal]:
    """Returns (spread_bps, liquidity_score in [0, 1])."""
    if order_book is None or not order_book.bids or not order_book.asks:
        return Decimal("0.0"), Decimal("0.0")

    best_bid = order_book.bids[0].price
    best_ask = order_book.asks[0].price
    mid = (best_bid + best_ask) / Decimal("2")
    if mid <= Decimal("0"):
        return Decimal("0.0"), Decimal("0.0")

    spread_bps = ((best_ask - best_bid) / mid * Decimal("10000")).quantize(Decimal("0.01"))

    bid_depth = sum((lvl.price * lvl.quantity for lvl in order_book.bids), Decimal("0"))
    ask_depth = sum((lvl.price * lvl.quantity for lvl in order_book.asks), Decimal("0"))
    depth_notional = min(bid_depth, ask_depth)
    liquidity_score = min(depth_notional / config.liquidity_target_notional_usd, Decimal("1.0"))

    return spread_bps, liquidity_score


class RecommendationService:
    def __init__(
        self,
        market_data_provider: Optional[MarketDataProvider] = None,
        decision_svc: DecisionService = decision_service,
        prediction_svc: PredictionService = prediction_service,
        evidence_svc: EvidenceService = evidence_service,
        config: RecommendationConfig = recommendation_config,
        store: ProposalStore = proposal_store,
        exchange: str = "binance",
    ) -> None:
        self._provider = market_data_provider or MarketDataProviderFactory.create_provider("binance")
        self._decision_service = decision_svc
        self._prediction_service = prediction_svc
        self._evidence_service = evidence_svc
        self._config = config
        self._store = store
        self._exchange = exchange
        self._regime_agent = MarketRegimeAgent()

    async def _fetch_candles(self, symbol: str, timeframe: Timeframe) -> Sequence[Candle]:
        minutes = _TIMEFRAME_MINUTES[timeframe]
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes * self._config.candle_lookback_periods)
        try:
            candles = await self._provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=self._config.candle_lookback_periods,
            )
        except Exception as exc:  # noqa: BLE001 - translate any adapter failure uniformly
            raise MarketDataUnavailableError(f"fetch_candles failed for {symbol}/{timeframe.value}: {exc}") from exc

        # Defensive re-validation, independent of the provider's own `is_closed` flag: a
        # kline whose close_time is still in the future cannot actually be closed yet.
        # (Binance's public REST API always reports closeTime = open_time + interval - 1ms
        # for the currently-forming candle too, and this repo's BinancePublicMarketDataProvider
        # marks every returned kline is_closed=True -- see packages/market_data/adapters/
        # binance.py. Trusting that blindly would let a not-yet-closed candle drive
        # `as_of_time`/`reference_price`, and would show a nonsensical negative freshness to
        # the user.) Never widen this list, never mark a filtered-out candle as usable.
        wall_clock_now = datetime.now(timezone.utc)
        candles = [c for c in candles if c.close_time <= wall_clock_now]

        if not candles:
            raise MarketDataUnavailableError(f"No confirmed-closed candles returned for {symbol}/{timeframe.value}")
        return candles

    async def _fetch_order_book(self, symbol: str) -> Optional[OrderBookSnapshot]:
        try:
            return await self._provider.fetch_order_book_snapshot(symbol, depth=self._config.order_book_depth_levels)
        except Exception:  # noqa: BLE001 - liquidity facts degrade gracefully, they don't block a scan
            return None

    # ------------------------------------------------------------------------------
    # get_market_overview
    # ------------------------------------------------------------------------------

    async def get_market_overview(self, symbols: List[str], timeframes: List[str]) -> MarketOverview:
        now = datetime.now(timezone.utc)
        symbol_overviews: List[SymbolMarketOverview] = []

        for symbol in symbols:
            tf_snapshots: List[TimeframeSnapshot] = []
            reason_codes: List[str] = []
            last_price: Optional[Decimal] = None
            last_data_timestamp: Optional[datetime] = None
            worst_freshness: Optional[float] = None
            any_timeframe_stale = False

            for tf_str in timeframes:
                try:
                    timeframe = _parse_timeframe(tf_str)
                    candles = await self._fetch_candles(symbol, timeframe)
                except MarketDataUnavailableError as exc:
                    reason_codes.append(f"{tf_str}:UNAVAILABLE:{exc}")
                    continue

                as_of_time = max(c.close_time for c in candles if c.is_closed)
                req = FeatureComputationRequest(
                    exchange=self._exchange, symbol=symbol, timeframe=timeframe,
                    feature_set="standard_v1", as_of_time=as_of_time,
                )
                snapshot = feature_pipeline.compute(req, list(candles))
                latest_close = max((c for c in candles if c.is_closed), key=lambda c: c.close_time).close_price

                ctx = AgentEvaluationContext(
                    exchange=self._exchange, symbol=symbol, timeframe=timeframe, as_of_time=as_of_time,
                    feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN,
                    data_quality_status="HEALTHY", reference_price=latest_close,
                    strategy_config=default_strategy_config,
                )
                regime = self._regime_agent.classify_regime(ctx)
                freshness = (now - as_of_time).total_seconds()

                tf_snapshots.append(
                    TimeframeSnapshot(
                        timeframe=tf_str,
                        market_regime=regime.value,
                        volatility_bucket=_volatility_bucket(
                            snapshot.values.get("volatility_20"), default_strategy_config
                        ),
                        last_close=latest_close,
                        close_time=as_of_time,
                        freshness_seconds=freshness,
                    )
                )
                last_price = latest_close
                if last_data_timestamp is None or as_of_time > last_data_timestamp:
                    last_data_timestamp = as_of_time
                worst_freshness = freshness if worst_freshness is None else max(worst_freshness, freshness)
                if freshness > max_allowed_staleness_seconds(tf_str, self._config):
                    any_timeframe_stale = True

            if not tf_snapshots:
                symbol_overviews.append(
                    SymbolMarketOverview(
                        symbol=symbol, market_status=MarketStatus.UNAVAILABLE, reason_codes=reason_codes
                    )
                )
                continue

            order_book = await self._fetch_order_book(symbol)
            _spread_bps, liquidity_score = _liquidity_facts(order_book, self._config)
            liquidity_status = (
                "UNKNOWN" if order_book is None
                else "NORMAL" if liquidity_score >= self._config.min_liquidity_score
                else "THIN"
            )

            status = MarketStatus.STALE if any_timeframe_stale else MarketStatus.NORMAL

            symbol_overviews.append(
                SymbolMarketOverview(
                    symbol=symbol,
                    market_status=status,
                    last_price=last_price,
                    data_timestamp=last_data_timestamp,
                    freshness_seconds=worst_freshness,
                    liquidity_status=liquidity_status,
                    timeframes=tf_snapshots,
                    reason_codes=reason_codes,
                )
            )

        overall = MarketStatus.NORMAL
        if symbol_overviews and all(s.market_status == MarketStatus.UNAVAILABLE for s in symbol_overviews):
            overall = MarketStatus.UNAVAILABLE
        elif any(s.market_status != MarketStatus.NORMAL for s in symbol_overviews):
            overall = MarketStatus.STALE

        return MarketOverview(generated_at=now, overall_market_status=overall, symbols=symbol_overviews)

    # ------------------------------------------------------------------------------
    # scan_trade_opportunities
    # ------------------------------------------------------------------------------

    def _build_candidate(
        self,
        decision_result: DecisionResult,
        symbol: str,
        timeframe: Timeframe,
        spread_bps: Decimal,
        liquidity_score: Decimal,
        now: datetime,
    ) -> Optional[TradeCandidate]:
        intent = decision_result.trade_intent
        if intent is None:
            return None

        accepted_ids = set(decision_result.consensus.accepted_signals)
        contributing = [s for s in decision_result.signals if s.signal_id in accepted_ids]
        strategy_names = sorted({s.agent_id for s in contributing}) or [PIPELINE_STRATEGY_NAME]

        data_timestamp = decision_result.feature_snapshot.lookback_end
        freshness = (now - data_timestamp).total_seconds()

        lineage = DecisionLineage(
            feature_snapshot_id=str(decision_result.feature_snapshot.snapshot_id),
            market_regime=decision_result.market_regime.value,
            signal_ids=[str(s.signal_id) for s in decision_result.signals],
            critic_decision_ids=[str(d.decision_id) for d in decision_result.critic_decisions],
            consensus_id=str(decision_result.consensus.consensus_id),
            allocation_id=str(decision_result.allocation.allocation_id),
            trade_intent_id=str(intent.intent_id),
            config_hash=decision_result.strategy_config_hash,
        )

        return TradeCandidate(
            symbol=symbol,
            side=intent.side.value,
            timeframe=timeframe.value,
            horizon_minutes=intent.horizon_minutes,
            strategy_names=strategy_names,
            strategy_version=PIPELINE_STRATEGY_VERSION,
            reference_price=intent.reference_price,
            stop_loss=intent.suggested_stop_price,
            take_profit=intent.suggested_take_profit_price,
            raw_confidence=intent.weighted_confidence,
            expected_return_bps=intent.expected_return_bps,
            net_edge_bps=intent.net_edge_bps,
            market_regime=decision_result.market_regime.value,
            liquidity_score=liquidity_score,
            spread_bps=spread_bps,
            reason_codes=intent.reason_codes,
            feature_snapshot_id=str(decision_result.feature_snapshot.snapshot_id),
            feature_set_version=decision_result.feature_snapshot.feature_set_version,
            data_timestamp=data_timestamp,
            freshness_seconds=freshness,
            config_hash=decision_result.strategy_config_hash,
            decision_lineage=lineage,
        )

    async def scan_trade_opportunities(
        self,
        symbols: List[str],
        timeframes: List[str],
        max_results: Optional[int] = None,
    ) -> RecommendationResult:
        now = datetime.now(timezone.utc)
        max_results = max_results or self._config.max_proposals

        built_proposals: List = []
        no_trade_reasons: List[str] = []
        no_trade_symbols: List[str] = []
        symbols_evaluated: List[str] = []
        unavailable_pairs = 0
        total_pairs = 0
        pipeline_evidence: Optional[StrategyEvidence] = None

        for symbol in symbols:
            symbols_evaluated.append(symbol)
            symbol_had_proposal = False

            for tf_str in timeframes:
                total_pairs += 1
                try:
                    timeframe = _parse_timeframe(tf_str)
                    candles = await self._fetch_candles(symbol, timeframe)
                except MarketDataUnavailableError as exc:
                    unavailable_pairs += 1
                    no_trade_reasons.append(f"{symbol}/{tf_str}: MARKET_UNAVAILABLE ({exc})")
                    continue

                as_of_time = max(c.close_time for c in candles if c.is_closed)
                reference_price = max((c for c in candles if c.is_closed), key=lambda c: c.close_time).close_price

                decision_result = await self._decision_service.decide(
                    exchange=self._exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=list(candles),
                    as_of_time=as_of_time,
                    reference_price=reference_price,
                )

                if decision_result.trade_intent is None:
                    no_trade_reasons.append(
                        f"{symbol}/{tf_str}: {', '.join(decision_result.allocation.reason_codes) or 'NO_TRADE'}"
                    )
                    continue

                order_book = await self._fetch_order_book(symbol)
                spread_bps, liquidity_score = _liquidity_facts(order_book, self._config)

                candidate = self._build_candidate(decision_result, symbol, timeframe, spread_bps, liquidity_score, now)
                if candidate is None:
                    continue

                evidence_for_pair = self._evidence_service.get_evidence(
                    PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION,
                    config_hash=candidate.config_hash, feature_version=candidate.feature_set_version, now=now,
                )
                pipeline_evidence = evidence_for_pair
                prediction = self._prediction_service.predict(
                    symbol, tf_str, candidate.horizon_minutes, decision_result.feature_snapshot
                )

                passed, reasons = check_candidate_gates(candidate, prediction, evidence_for_pair, self._config)
                if not passed:
                    no_trade_reasons.append(f"{symbol}/{tf_str}: {', '.join(reasons)}")
                    continue

                proposal = proposal_builder.build(candidate, prediction, evidence_for_pair, self._config, now)
                if proposal is None:
                    no_trade_reasons.append(f"{symbol}/{tf_str}: PROPOSAL_BUILD_FAILED")
                    continue

                self._store.put(proposal)
                built_proposals.append(proposal)
                symbol_had_proposal = True

            if not symbol_had_proposal:
                no_trade_symbols.append(symbol)

        if pipeline_evidence is None:
            pipeline_evidence = self._evidence_service.get_evidence(
                PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION,
                config_hash="", feature_version="standard_v1", now=now,
            )

        ranked = opportunity_ranker.rank(built_proposals, max_results=max_results)

        if total_pairs > 0 and unavailable_pairs == total_pairs:
            status = RecommendationStatus.MARKET_UNAVAILABLE
        elif ranked:
            status = RecommendationStatus.PROPOSALS_AVAILABLE
        elif pipeline_evidence.status.value != "APPROVED":
            status = RecommendationStatus.STRATEGY_NOT_APPROVED
        elif no_trade_reasons and all("INSUFFICIENT_EVIDENCE_PREDICTION_UNAVAILABLE" in r for r in no_trade_reasons):
            status = RecommendationStatus.INSUFFICIENT_EVIDENCE
        else:
            status = RecommendationStatus.NO_TRADE

        market_status = (
            MarketStatus.UNAVAILABLE if status == RecommendationStatus.MARKET_UNAVAILABLE else MarketStatus.NORMAL
        )

        return RecommendationResult(
            request_id=str(uuid4()),
            status=status,
            generated_at=now,
            market_status=market_status,
            proposals=ranked,
            rejected_candidates=max(0, len(built_proposals) - len(ranked)),
            no_trade_reasons=no_trade_reasons,
            symbols_evaluated=symbols_evaluated,
            no_trade_symbols=no_trade_symbols,
        )


recommendation_service = RecommendationService()
