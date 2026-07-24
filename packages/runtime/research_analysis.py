"""Public-data, deterministic research analysis runtime for the dashboard.

This runtime intentionally stops before model/LLM approval authority.  It uses only closed
public Binance spot candles, the existing feature pipeline, regime router, rule-based strategy
agents, critic, consensus and allocator.  A completed analysis can therefore be AVAILABLE
while still returning NO_DECISION.  It never turns a rule-based signal into execution
authority: Verification is not run without the Phase 6 specialist set and Risk always denies
trade authority in this research-only surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Sequence

from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.agents.strategy_config import default_strategy_config
from packages.features.models import FeatureComputationRequest, FeatureQualityStatus
from packages.features.pipeline import feature_pipeline
from packages.governance.decision_service import decision_service
from packages.governance.strategy_router import route
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.historical_quality import (
    TIMEFRAME_INTERVAL,
    DatasetQualityStatus,
    validate_historical_series,
)
from packages.market_data.models import Candle, Timeframe
from packages.retraining.xgboost_contracts import PRICE_FEATURE_NAMES
from packages.runtime.llm_research import PublicLLMResearchRuntime

PublicCandlesFetcher = Callable[
    [str, Timeframe, datetime, datetime, int],
    Awaitable[Sequence[Candle]],
]
Clock = Callable[[], datetime]

_MINIMUM_CANDLE_COUNT = 50
_LOOKBACK_BARS = 380
_SUPPORTED_SYMBOLS = frozenset({"BTC/USDT", "ETH/USDT"})
_CANDLE_PUBLICATION_LAG = timedelta(milliseconds=1)

_FEATURE_UNITS = {
    "return_1p": "ratio",
    "return_3p": "ratio",
    "return_5p": "ratio",
    "high_low_range": "ratio",
    "ema_20_slope": "ratio",
    "adx_14": "index",
    "rsi_14": "index",
    "atr_14": "quote_currency",
    "volatility_20": "ratio",
    "relative_volume_20": "ratio",
    "zscore_20": "index",
    "bollinger_pos_20": "ratio",
    "donchian_breakout_20": "signal",
}


@dataclass(frozen=True)
class ResearchAnalysisResult:
    status: str
    recommendation: str
    reason_codes: tuple[str, ...]
    as_of_time: datetime | None
    agents: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    debate: dict[str, object]
    verification: dict[str, object]
    risk: dict[str, object]


class PublicResearchAnalysisRuntime:
    """Runs an honest research-only analysis from public, point-in-time market data."""

    def __init__(
        self,
        fetch_candles: PublicCandlesFetcher | None = None,
        clock: Clock | None = None,
        llm_runtime: PublicLLMResearchRuntime | None = None,
    ) -> None:
        provider = BinancePublicMarketDataProvider()
        self._fetch_candles = fetch_candles or provider.fetch_candles
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._llm_runtime = (
            llm_runtime or PublicLLMResearchRuntime.from_environment()
        )

    @property
    def supported_symbols(self) -> frozenset[str]:
        return _SUPPORTED_SYMBOLS

    @property
    def llm_specialists_configured(self) -> bool:
        return self._llm_runtime.configured

    async def analyze(
        self,
        *,
        analysis_id: str,
        symbol: str,
        timeframe: Timeframe,
    ) -> ResearchAnalysisResult:
        if symbol not in _SUPPORTED_SYMBOLS:
            return _unavailable("ANALYSIS_SCOPE_UNSUPPORTED")

        requested_at = self._clock()
        if requested_at.tzinfo is None:
            return _unavailable("ANALYSIS_CLOCK_INVALID")

        interval = TIMEFRAME_INTERVAL[timeframe]
        start_time = requested_at - interval * _LOOKBACK_BARS
        try:
            raw_candles = list(
                await self._fetch_candles(
                    symbol,
                    timeframe,
                    start_time,
                    requested_at,
                    500,
                )
            )
        except Exception:  # noqa: BLE001 - provider errors are converted to safe unavailable state
            return _unavailable("PUBLIC_MARKET_DATA_UNAVAILABLE")

        if any(
            candle.exchange != "binance"
            or candle.symbol != symbol
            or candle.timeframe != timeframe
            for candle in raw_candles
        ):
            return _unavailable("MARKET_DATA_SCOPE_MISMATCH")

        available_candles = [
            candle
            for candle in raw_candles
            if candle.close_time + _CANDLE_PUBLICATION_LAG <= requested_at
        ]
        clean_candles, quality = validate_historical_series(
            available_candles,
            timeframe,
            as_of=requested_at,
        )
        if quality.status == DatasetQualityStatus.REJECTED:
            return _unavailable("MARKET_DATA_QUALITY_REJECTED")
        if quality.status == DatasetQualityStatus.DEGRADED:
            return _unavailable("MARKET_DATA_QUALITY_DEGRADED")
        if len(clean_candles) < _MINIMUM_CANDLE_COUNT:
            return _unavailable("INSUFFICIENT_CANDLE_HISTORY")

        observed_at = clean_candles[-1].close_time
        source_available_at = observed_at + _CANDLE_PUBLICATION_LAG
        if source_available_at > requested_at:
            return _unavailable("MARKET_DATA_NOT_YET_AVAILABLE")
        if requested_at - source_available_at > interval + timedelta(minutes=5):
            return _unavailable("MARKET_DATA_STALE")
        request = FeatureComputationRequest(
            exchange="binance",
            symbol=symbol,
            timeframe=timeframe,
            feature_set="standard_v1",
            as_of_time=source_available_at,
        )
        snapshot = feature_pipeline.compute(request, clean_candles)
        if snapshot.quality_status != FeatureQualityStatus.VALID:
            return _unavailable("FEATURE_SNAPSHOT_UNAVAILABLE")

        reference_price = clean_candles[-1].close_price
        regime_context = AgentEvaluationContext(
            exchange="binance",
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=source_available_at,
            feature_snapshot=snapshot,
            market_regime=MarketRegime.UNKNOWN,
            data_quality_status="HEALTHY",
            reference_price=reference_price,
            strategy_config=default_strategy_config,
        )
        regime = MarketRegimeAgent().classify_regime_detailed(regime_context)
        routing = route(regime.regime)
        decision = await decision_service.decide(
            exchange="binance",
            symbol=symbol,
            timeframe=timeframe,
            candles=clean_candles,
            as_of_time=source_available_at,
            reference_price=reference_price,
            strategy_config=default_strategy_config,
            allowed_strategy_types=routing.allowed_strategy_types,
        )
        if decision.market_regime != regime.regime:
            return _unavailable("REGIME_RUNTIME_INCONSISTENT")

        critics_by_signal = {
            critic.signal_id: critic
            for critic in decision.critic_decisions
        }
        agents: list[dict[str, object]] = [
            {
                "agent_name": "regime_agent_v1",
                "status": "AVAILABLE",
                "regime": regime.regime.value,
                "heuristic_score": str(regime.confidence),
                "score_type": "HEURISTIC_SCORE",
                "reason_codes": list(regime.reason_codes),
                "as_of_time": source_available_at.isoformat(),
            },
            {
                "agent_name": "strategy_router_v1",
                "status": "AVAILABLE",
                "allowed_strategy_types": sorted(
                    strategy.value for strategy in routing.allowed_strategy_types
                ),
                "reason_codes": list(routing.reason_codes),
                "as_of_time": source_available_at.isoformat(),
            },
        ]
        for signal in decision.signals:
            critic = critics_by_signal[signal.signal_id]
            agents.append(
                {
                    "agent_name": signal.agent_id,
                    "status": "AVAILABLE",
                    "action": signal.action.value,
                    "heuristic_score": str(signal.confidence),
                    "score_type": signal.confidence_type,
                    "return_proxy_bps": (
                        str(signal.expected_return_bps)
                        if signal.expected_return_bps is not None
                        else None
                    ),
                    "return_proxy_type": "TARGET_DISTANCE_HEURISTIC_PROXY",
                    "critic_approved": critic.approved_for_aggregation,
                    "critic_adjusted_score": str(critic.adjusted_confidence),
                    "reason_codes": [
                        *signal.reason_codes,
                        *critic.warning_codes,
                        *critic.rejection_codes,
                    ],
                    "as_of_time": source_available_at.isoformat(),
                }
            )
        agents.extend(
            (
                {
                    "agent_name": "quantitative_agent",
                    "status": "UNAVAILABLE",
                    "reason_codes": ["QUANTITATIVE_RUNTIME_NOT_BOUND"],
                },
            )
        )

        technical_evidence = tuple(
            _feature_evidence(
                analysis_id=analysis_id,
                name=name,
                value=snapshot.values[name],
                snapshot_id=str(snapshot.snapshot_id),
                observed_at=observed_at,
                available_at=source_available_at,
                candle_count=snapshot.lineage.candle_count_used,
            )
            for name in PRICE_FEATURE_NAMES
            if snapshot.values[name] is not None
        )
        llm_result = await self._llm_runtime.analyze(
            analysis_id=analysis_id,
            symbol=symbol,
            analysis_time=requested_at,
        )
        agents.extend(llm_result.agents)
        evidence = (*technical_evidence, *llm_result.evidence)

        has_trade_intent = decision.trade_intent is not None
        recommendation = "RESEARCH_LONG" if has_trade_intent else "NO_DECISION"
        reason_codes = (
            "RESEARCH_ONLY",
            *routing.reason_codes,
            *decision.allocation.reason_codes,
            *(
                ("GROUNDED_LLM_CONTEXT_AVAILABLE",)
                if llm_result.status == "AVAILABLE"
                else ()
            ),
        )
        return ResearchAnalysisResult(
            status="AVAILABLE",
            recommendation=recommendation,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            as_of_time=(
                llm_result.as_of_time
                if llm_result.status in {"AVAILABLE", "PARTIAL"}
                else source_available_at
            ),
            agents=tuple(agents),
            evidence=evidence,
            debate=llm_result.debate,
            verification=llm_result.verification,
            risk={
                "allow_trade": False,
                "approved_quantity": "0",
                "approved_notional": "0",
                "reason_codes": list(llm_result.risk_reason_codes),
            },
        )


def _feature_evidence(
    *,
    analysis_id: str,
    name: str,
    value: Decimal | int | bool | None,
    snapshot_id: str,
    observed_at: datetime,
    available_at: datetime,
    candle_count: int,
) -> dict[str, object]:
    return {
        "evidence_id": f"{analysis_id}:technical:{name}",
        "category": "TECHNICAL",
        "name": name,
        "numeric_value": str(value),
        "unit": _FEATURE_UNITS[name],
        "status": "VALID",
        "source_id": "binance_public_rest",
        "feature_snapshot_id": snapshot_id,
        "feature_set": "standard_v1",
        "feature_set_version": "1.0.0",
        "observed_at": observed_at.isoformat(),
        "available_at": available_at.isoformat(),
        "candle_count": candle_count,
    }


def _unavailable(reason_code: str) -> ResearchAnalysisResult:
    return ResearchAnalysisResult(
        status="UNAVAILABLE",
        recommendation="NO_DECISION",
        reason_codes=(reason_code,),
        as_of_time=None,
        agents=(),
        evidence=(),
        debate={
            "status": "NOT_RUN",
            "reason_codes": ["UPSTREAM_ANALYSIS_UNAVAILABLE"],
            "turns": [],
        },
        verification={
            "decision": "REJECTED",
            "reason_codes": ["UPSTREAM_ANALYSIS_UNAVAILABLE"],
        },
        risk={
            "allow_trade": False,
            "approved_quantity": "0",
            "approved_notional": "0",
            "reason_codes": ["UPSTREAM_ANALYSIS_UNAVAILABLE"],
        },
    )
