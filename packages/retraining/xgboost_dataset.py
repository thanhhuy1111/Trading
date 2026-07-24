"""Deterministic point-in-time dataset and three-class label construction.

Only real caller-provided candles and derivatives snapshots are accepted. Missing lineage,
irregular derivatives cadence, future availability, gaps, and source mismatches are explicit
rejections; no value is imputed and price-plus-derivatives never falls back to price-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from packages.common.immutable import FrozenMapping
from packages.features.calculators.derivatives import (
    FundingRateZScoreCalculator,
    OpenInterestRateOfChangeCalculator,
)
from packages.features.derivatives_models import DerivativesFeatureContext
from packages.features.models import FeatureComputationRequest, FeatureQualityStatus
from packages.features.pipeline import feature_pipeline
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import Candle, DataQualityStatus, SymbolInfo, Timeframe
from packages.market_data.symbol_registry import symbol_registry
from packages.retraining.xgboost_contracts import (
    DATASET_VERSION,
    DERIVATIVES_FEATURE_NAMES,
    LABEL_THRESHOLD_CANDIDATES,
    LABEL_VERSION,
    PRICE_FEATURE_NAMES,
    PRICE_FEATURE_SET,
    ClassDistribution,
    DatasetBuildStatus,
    DatasetFeatureLineage,
    DatasetMode,
    DerivativesFeatureLineage,
    PriceFeatureLineage,
    TargetClass,
    XGBoostDatasetBuildResult,
    XGBoostDatasetReport,
    XGBoostDatasetSample,
    feature_schema_hash,
)

MVP_EXCHANGE_SYMBOL = "BTCUSDT"
MVP_CANONICAL_SYMBOL = "BTC/USDT"
SPOT_EXCHANGE = "binance"
DERIVATIVES_EXCHANGE = "binance_usdm_futures"
MVP_TIMEFRAME = Timeframe.H4

REQUIRED_DERIVATIVES_METRICS: Tuple[str, ...] = ("funding_rate", "open_interest")

PRICE_MIN_HISTORY = 29
PRICE_FEATURE_WINDOW = 60
VOLATILITY_LOOKBACK_RETURNS = 20
BAR_INTERVAL = timedelta(hours=4)
CANDLE_PUBLICATION_LAG = timedelta(milliseconds=1)
DERIVATIVES_REQUIRED_SAMPLES = 20
DERIVATIVES_CADENCE = timedelta(minutes=5)
DERIVATIVES_CADENCE_TOLERANCE = timedelta(minutes=1)
DERIVATIVES_MAX_AGE = timedelta(minutes=10)


def classify_target(
    future_return: Decimal,
    rolling_volatility: Decimal,
    threshold_k: Decimal,
) -> tuple[TargetClass, Decimal]:
    if rolling_volatility < 0:
        raise ValueError("rolling_volatility cannot be negative")
    if threshold_k <= 0:
        raise ValueError("threshold_k must be positive")
    threshold = threshold_k * rolling_volatility
    if future_return > threshold:
        return TargetClass.BULLISH, threshold
    if future_return < -threshold:
        return TargetClass.BEARISH, threshold
    return TargetClass.NEUTRAL, threshold


class XGBoostDatasetBuilder:
    def build(
        self,
        candles: Sequence[Candle],
        mode: DatasetMode,
        threshold_k: Decimal,
        derivatives_snapshots: Optional[Sequence[DerivativesSnapshot]] = None,
        exchange_symbol: str = MVP_EXCHANGE_SYMBOL,
        timeframe: Timeframe = MVP_TIMEFRAME,
    ) -> XGBoostDatasetBuildResult:
        schema_hash = feature_schema_hash(mode)
        symbol_info = _exact_symbol_info(exchange_symbol)
        global_reason = _validate_build_request(
            candles=candles,
            symbol_info=symbol_info,
            exchange_symbol=exchange_symbol,
            timeframe=timeframe,
            threshold_k=threshold_k,
        )
        if global_reason is not None:
            return _rejected_result(
                mode,
                schema_hash,
                len(candles),
                global_reason,
                threshold_k,
            )

        assert symbol_info is not None
        rejection_counts: Counter[str] = Counter()
        samples: List[XGBoostDatasetSample] = []
        candidate_count = max(0, len(candles) - 1)
        derivatives = list(derivatives_snapshots or [])

        for index in range(candidate_count):
            contiguous_start = _contiguous_segment_start(candles, index)
            contiguous_count = index - contiguous_start + 1
            if contiguous_count < PRICE_MIN_HISTORY:
                rejection_counts["INSUFFICIENT_PRICE_HISTORY"] += 1
                continue

            current = candles[index]
            future = candles[index + 1]
            if not _is_next_bar(current, future):
                rejection_counts["TARGET_GAP"] += 1
                continue

            window_start = max(contiguous_start, index + 1 - PRICE_FEATURE_WINDOW)
            price_window = list(candles[window_start : index + 1])
            as_of_time = _candle_available_at(current)
            target_time = _candle_available_at(future)

            snapshot = feature_pipeline.compute(
                FeatureComputationRequest(
                    exchange=SPOT_EXCHANGE,
                    symbol=symbol_info.canonical_symbol,
                    timeframe=timeframe,
                    feature_set=PRICE_FEATURE_SET,
                    as_of_time=as_of_time,
                    mode="batch",
                ),
                price_window,
            )
            price_values = _selected_price_values(snapshot.values)
            if price_values is None:
                rejection_counts["REQUIRED_PRICE_FEATURE_MISSING"] += 1
                continue

            rolling_volatility = _rolling_volatility(price_window)
            if rolling_volatility is None:
                rejection_counts["INSUFFICIENT_PRICE_HISTORY"] += 1
                continue

            future_return = future.close_price / current.close_price - Decimal("1")
            target_class, label_threshold = classify_target(
                future_return,
                rolling_volatility,
                threshold_k,
            )

            price_lineage = PriceFeatureLineage(
                source_exchange=SPOT_EXCHANGE,
                source_symbol=symbol_info.canonical_symbol,
                source_timeframe=timeframe.value,
                candle_count_used=snapshot.lineage.candle_count_used,
                oldest_candle_timestamp=snapshot.lineage.oldest_candle_timestamp,
                newest_candle_timestamp=snapshot.lineage.newest_candle_timestamp,
                source_available_at=as_of_time,
                calculator_versions=FrozenMapping(
                    {
                        name: snapshot.lineage.calculator_versions[name]
                        for name in PRICE_FEATURE_NAMES
                    }
                ),
            )

            derivative_values: Dict[str, Decimal] = {}
            derivative_lineage: Optional[DerivativesFeatureLineage] = None
            derivatives_available_at: Optional[datetime] = None
            derivative_audit: Dict[str, datetime] = {}
            if mode == DatasetMode.PRICE_PLUS_DERIVATIVES:
                derivative_result = _derivatives_for_as_of(
                    derivatives,
                    symbol_info.canonical_symbol,
                    as_of_time,
                )
                if derivative_result.reason_code is not None:
                    rejection_counts[derivative_result.reason_code] += 1
                    continue
                derivative_values = derivative_result.values
                derivative_lineage = derivative_result.lineage
                derivatives_available_at = derivative_result.available_at
                derivative_audit = derivative_result.ingestion_audit

            feature_values = {**price_values, **derivative_values}
            feature_names = tuple(feature_values)
            expected_names = (
                PRICE_FEATURE_NAMES
                if mode == DatasetMode.PRICE_ONLY
                else PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
            )
            if feature_names != expected_names:
                rejection_counts["FEATURE_SCHEMA_MISMATCH"] += 1
                continue

            feature_available_at = max(
                timestamp
                for timestamp in (as_of_time, derivatives_available_at)
                if timestamp is not None
            )
            sample_id = _sample_id(
                mode=mode,
                schema_hash=schema_hash,
                exchange_symbol=exchange_symbol,
                canonical_symbol=symbol_info.canonical_symbol,
                timeframe=timeframe,
                as_of_time=as_of_time,
                target_time=target_time,
            )
            reason_codes: Tuple[str, ...] = ()
            if snapshot.quality_status == FeatureQualityStatus.DEGRADED:
                reason_codes = ("UNSELECTED_PRICE_FEATURES_DEGRADED",)

            samples.append(
                XGBoostDatasetSample(
                    sample_id=sample_id,
                    exchange_symbol=exchange_symbol,
                    canonical_symbol=symbol_info.canonical_symbol,
                    spot_exchange=SPOT_EXCHANGE,
                    derivatives_exchange=(
                        DERIVATIVES_EXCHANGE
                        if mode == DatasetMode.PRICE_PLUS_DERIVATIVES
                        else None
                    ),
                    timeframe=timeframe,
                    as_of_time=as_of_time,
                    target_time=target_time,
                    close_at_as_of=current.close_price,
                    future_close=future.close_price,
                    future_return=future_return,
                    rolling_volatility=rolling_volatility,
                    label_threshold_k=threshold_k,
                    label_threshold=label_threshold,
                    target_class=target_class,
                    dataset_mode=mode,
                    feature_names=feature_names,
                    feature_values=FrozenMapping(feature_values),
                    feature_status=snapshot.quality_status,
                    feature_lineage=DatasetFeatureLineage(
                        price=price_lineage,
                        derivatives=derivative_lineage,
                    ),
                    feature_available_at=feature_available_at,
                    ingestion_audit=FrozenMapping(
                        {
                            "price_received_at": current.received_timestamp,
                            **derivative_audit,
                        }
                    ),
                    reason_codes=reason_codes,
                    dataset_version=DATASET_VERSION,
                )
            )

        samples.sort(key=lambda sample: (sample.as_of_time, sample.sample_id))
        return _result_from_samples(
            mode=mode,
            schema_hash=schema_hash,
            input_candle_count=len(candles),
            candidate_count=candidate_count,
            samples=samples,
            rejection_counts=rejection_counts,
            threshold_k=threshold_k,
        )


class _DerivativesSelection:
    def __init__(
        self,
        values: Optional[Dict[str, Decimal]] = None,
        lineage: Optional[DerivativesFeatureLineage] = None,
        available_at: Optional[datetime] = None,
        ingestion_audit: Optional[Dict[str, datetime]] = None,
        reason_code: Optional[str] = None,
    ) -> None:
        self.values = values or {}
        self.lineage = lineage
        self.available_at = available_at
        self.ingestion_audit = ingestion_audit or {}
        self.reason_code = reason_code


def _derivatives_for_as_of(
    snapshots: Sequence[DerivativesSnapshot],
    canonical_symbol: str,
    as_of_time: datetime,
) -> _DerivativesSelection:
    if not snapshots:
        return _DerivativesSelection(reason_code="DERIVATIVES_HISTORY_MISSING")

    eligible: List[DerivativesSnapshot] = []
    delayed_seen = False
    for snapshot in snapshots:
        lineages = [snapshot.metric_lineage.get(metric) for metric in REQUIRED_DERIVATIVES_METRICS]
        known_lineages = [lineage for lineage in lineages if lineage is not None]
        event_is_relevant = any(lineage.event_time <= as_of_time for lineage in known_lineages)
        if event_is_relevant and (
            snapshot.symbol != canonical_symbol or snapshot.exchange != DERIVATIVES_EXCHANGE
        ):
            return _DerivativesSelection(reason_code="DERIVATIVES_SOURCE_MISMATCH")
        if len(known_lineages) != len(REQUIRED_DERIVATIVES_METRICS):
            if snapshot.exchange_timestamp <= as_of_time:
                return _DerivativesSelection(reason_code="DERIVATIVES_LINEAGE_MISSING")
            continue
        if any(
            lineage.available_at < snapshot.received_timestamp
            for lineage in known_lineages
        ):
            return _DerivativesSelection(reason_code="DERIVATIVES_LINEAGE_INVALID")
        if snapshot.data_quality_status != DataQualityStatus.HEALTHY:
            if all(lineage.available_at <= as_of_time for lineage in known_lineages):
                return _DerivativesSelection(reason_code="DERIVATIVES_SOURCE_UNHEALTHY")
            continue
        if any(lineage.event_time > as_of_time for lineage in known_lineages):
            continue
        if any(lineage.available_at > as_of_time for lineage in known_lineages):
            delayed_seen = True
            continue
        if snapshot.funding_rate is None or snapshot.open_interest is None:
            continue
        eligible.append(snapshot)

    eligible.sort(
        key=lambda snapshot: max(
            snapshot.metric_lineage[metric].event_time
            for metric in REQUIRED_DERIVATIVES_METRICS
        )
    )
    if len(eligible) < DERIVATIVES_REQUIRED_SAMPLES:
        reason = (
            "DERIVATIVES_FUTURE_AVAILABILITY"
            if delayed_seen
            else "DERIVATIVES_HISTORY_MISSING"
        )
        return _DerivativesSelection(reason_code=reason)

    window = eligible[-DERIVATIVES_REQUIRED_SAMPLES:]
    for metric in REQUIRED_DERIVATIVES_METRICS:
        event_times = [snapshot.metric_lineage[metric].event_time for snapshot in window]
        if as_of_time - event_times[-1] > DERIVATIVES_MAX_AGE:
            return _DerivativesSelection(reason_code="DERIVATIVES_SNAPSHOT_STALE")
        for previous, current in zip(event_times, event_times[1:], strict=False):
            delta = current - previous
            if abs(delta - DERIVATIVES_CADENCE) > DERIVATIVES_CADENCE_TOLERANCE:
                return _DerivativesSelection(reason_code="DERIVATIVES_CADENCE_INVALID")

    context = DerivativesFeatureContext(
        exchange=DERIVATIVES_EXCHANGE,
        symbol=canonical_symbol,
        as_of_time=as_of_time,
    )
    calculators = (
        FundingRateZScoreCalculator(period=20),
        OpenInterestRateOfChangeCalculator(period=12),
    )
    values: Dict[str, Decimal] = {}
    calculator_versions: Dict[str, str] = {}
    for calculator in calculators:
        value = calculator.calculate(window, context)
        if not value.is_valid or value.value is None:
            return _DerivativesSelection(reason_code="DERIVATIVES_FEATURES_INVALID")
        values[calculator.name] = _as_decimal(value.value)
        calculator_versions[calculator.name] = calculator.version

    all_lineages = [
        snapshot.metric_lineage[metric]
        for snapshot in window
        for metric in REQUIRED_DERIVATIVES_METRICS
    ]
    available_at = max(lineage.available_at for lineage in all_lineages)
    event_times = [lineage.event_time for lineage in all_lineages]
    metric_lineage = {
        metric: tuple(snapshot.metric_lineage[metric] for snapshot in window)
        for metric in REQUIRED_DERIVATIVES_METRICS
    }
    lineage = DerivativesFeatureLineage(
        source_exchange=DERIVATIVES_EXCHANGE,
        source_symbol=canonical_symbol,
        sample_count=len(window),
        oldest_sample_timestamp=min(event_times),
        newest_sample_timestamp=max(event_times),
        cadence_seconds=int(DERIVATIVES_CADENCE.total_seconds()),
        cadence_tolerance_seconds=int(DERIVATIVES_CADENCE_TOLERANCE.total_seconds()),
        metric_lineage=FrozenMapping(metric_lineage),
        calculator_versions=FrozenMapping(calculator_versions),
    )
    audit = {
        f"derivatives_received_at_{index:02d}": snapshot.received_timestamp
        for index, snapshot in enumerate(window)
    }
    return _DerivativesSelection(
        values=values,
        lineage=lineage,
        available_at=available_at,
        ingestion_audit=audit,
    )


def _exact_symbol_info(exchange_symbol: str) -> Optional[SymbolInfo]:
    matches = [
        info
        for canonical_symbol in symbol_registry.list_canonical_symbols()
        if (info := symbol_registry.get_symbol_info(canonical_symbol)) is not None
        and info.exchange_symbol == exchange_symbol
    ]
    return matches[0] if len(matches) == 1 else None


def _validate_build_request(
    candles: Sequence[Candle],
    symbol_info: Optional[SymbolInfo],
    exchange_symbol: str,
    timeframe: Timeframe,
    threshold_k: Decimal,
) -> Optional[str]:
    if threshold_k <= 0:
        return "INVALID_THRESHOLD_K"
    if (
        symbol_info is None
        or exchange_symbol != MVP_EXCHANGE_SYMBOL
        or symbol_info.canonical_symbol != MVP_CANONICAL_SYMBOL
    ):
        return "UNSUPPORTED_SYMBOL"
    if timeframe != MVP_TIMEFRAME:
        return "UNSUPPORTED_TIMEFRAME"
    if not candles:
        return "CANDLES_EMPTY"
    previous_close: Optional[datetime] = None
    for candle in candles:
        if (
            candle.exchange != SPOT_EXCHANGE
            or candle.symbol != symbol_info.canonical_symbol
            or candle.timeframe != timeframe
        ):
            return "CANDLE_SOURCE_MISMATCH"
        if not candle.is_closed:
            return "CANDLE_NOT_CLOSED"
        if candle.data_quality_status != DataQualityStatus.HEALTHY:
            return "CANDLE_SOURCE_UNHEALTHY"
        if candle.open_time.tzinfo is None or candle.close_time.tzinfo is None:
            return "CANDLE_TIMESTAMP_INVALID"
        if candle.close_time - candle.open_time != BAR_INTERVAL - timedelta(
            milliseconds=1
        ):
            return "CANDLE_INTERVAL_INVALID"
        if candle.exchange_timestamp != candle.close_time:
            return "CANDLE_EVENT_TIME_MISMATCH"
        if previous_close is not None and candle.close_time <= previous_close:
            return "CANDLE_ORDER_INVALID"
        previous_close = candle.close_time
    return None


def _contiguous_segment_start(candles: Sequence[Candle], index: int) -> int:
    start = index
    while start > 0 and _is_next_bar(candles[start - 1], candles[start]):
        start -= 1
    return start


def _is_next_bar(current: Candle, future: Candle) -> bool:
    return (
        future.open_time - current.open_time == BAR_INTERVAL
        and future.close_time - current.close_time == BAR_INTERVAL
    )


def _candle_available_at(candle: Candle) -> datetime:
    return candle.close_time + CANDLE_PUBLICATION_LAG


def _selected_price_values(
    values: Dict[str, Optional[Decimal | int | bool]],
) -> Optional[Dict[str, Decimal]]:
    selected: Dict[str, Decimal] = {}
    for name in PRICE_FEATURE_NAMES:
        value = values.get(name)
        if value is None:
            return None
        selected[name] = _as_decimal(value)
    return selected


def _as_decimal(value: Decimal | int | bool) -> Decimal:
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def _rolling_volatility(candles: Sequence[Candle]) -> Optional[Decimal]:
    required = VOLATILITY_LOOKBACK_RETURNS + 1
    if len(candles) < required:
        return None
    window = candles[-required:]
    log_returns = [
        math.log(float(current.close_price) / float(previous.close_price))
        for previous, current in zip(window, window[1:], strict=False)
    ]
    mean_return = sum(log_returns) / len(log_returns)
    variance = sum((value - mean_return) ** 2 for value in log_returns) / len(log_returns)
    return Decimal(str(math.sqrt(variance)))


def _sample_id(
    mode: DatasetMode,
    schema_hash: str,
    exchange_symbol: str,
    canonical_symbol: str,
    timeframe: Timeframe,
    as_of_time: datetime,
    target_time: datetime,
) -> str:
    raw = "|".join(
        (
            DATASET_VERSION,
            mode.value,
            exchange_symbol,
            canonical_symbol,
            timeframe.value,
            as_of_time.isoformat(),
            target_time.isoformat(),
            schema_hash,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_from_samples(
    mode: DatasetMode,
    schema_hash: str,
    input_candle_count: int,
    candidate_count: int,
    samples: List[XGBoostDatasetSample],
    rejection_counts: Counter[str],
    threshold_k: Decimal,
) -> XGBoostDatasetBuildResult:
    status = DatasetBuildStatus.VALID if samples else DatasetBuildStatus.REJECTED
    checksum = _dataset_checksum(samples)
    class_distribution = _class_distribution(samples)
    report = XGBoostDatasetReport(
        status=status,
        dataset_mode=mode,
        dataset_version=DATASET_VERSION,
        label_version=LABEL_VERSION,
        label_threshold_k=threshold_k,
        feature_schema_hash=schema_hash,
        dataset_checksum=checksum,
        input_candle_count=input_candle_count,
        candidate_count=candidate_count,
        accepted_count=len(samples),
        rejected_count=candidate_count - len(samples),
        rejection_counts=FrozenMapping(dict(sorted(rejection_counts.items()))),
        request_rejection_codes=(),
        class_distribution=class_distribution,
        candidate_class_distributions=FrozenMapping(
            _candidate_class_distributions(samples)
        ),
        start_time=samples[0].as_of_time if samples else None,
        end_time=samples[-1].as_of_time if samples else None,
    )
    reason_codes = () if samples else tuple(sorted(rejection_counts)) or ("NO_VALID_SAMPLES",)
    return XGBoostDatasetBuildResult(
        status=status,
        dataset_mode=mode,
        samples=tuple(samples),
        report=report,
        reason_codes=reason_codes,
    )


def _rejected_result(
    mode: DatasetMode,
    schema_hash: str,
    input_candle_count: int,
    reason_code: str,
    threshold_k: Decimal,
) -> XGBoostDatasetBuildResult:
    candidate_count = 0
    empty_distribution = ClassDistribution(
        counts=FrozenMapping({target.value: 0 for target in TargetClass}),
        shares=FrozenMapping({target.value: 0.0 for target in TargetClass}),
    )
    report = XGBoostDatasetReport(
        status=DatasetBuildStatus.REJECTED,
        dataset_mode=mode,
        dataset_version=DATASET_VERSION,
        label_version=LABEL_VERSION,
        label_threshold_k=threshold_k,
        feature_schema_hash=schema_hash,
        dataset_checksum=_sha256([]),
        input_candle_count=input_candle_count,
        candidate_count=candidate_count,
        accepted_count=0,
        rejected_count=0,
        rejection_counts=FrozenMapping({}),
        request_rejection_codes=(reason_code,),
        class_distribution=empty_distribution,
        candidate_class_distributions=FrozenMapping(
            {
                format(candidate, ".2f"): empty_distribution
                for candidate in LABEL_THRESHOLD_CANDIDATES
            }
        ),
    )
    return XGBoostDatasetBuildResult(
        status=DatasetBuildStatus.REJECTED,
        dataset_mode=mode,
        samples=(),
        report=report,
        reason_codes=(reason_code,),
    )


def _class_distribution(samples: Sequence[XGBoostDatasetSample]) -> ClassDistribution:
    counts = {target.value: 0 for target in TargetClass}
    for sample in samples:
        counts[sample.target_class.value] += 1
    total = len(samples)
    shares = {
        target: (count / total if total else 0.0)
        for target, count in counts.items()
    }
    return ClassDistribution(
        counts=FrozenMapping(counts),
        shares=FrozenMapping(shares),
    )


def _candidate_class_distributions(
    samples: Sequence[XGBoostDatasetSample],
) -> Dict[str, ClassDistribution]:
    distributions: Dict[str, ClassDistribution] = {}
    for candidate in LABEL_THRESHOLD_CANDIDATES:
        counts = {target.value: 0 for target in TargetClass}
        for sample in samples:
            target, _ = classify_target(
                sample.future_return,
                sample.rolling_volatility,
                candidate,
            )
            counts[target.value] += 1
        total = len(samples)
        distributions[format(candidate, ".2f")] = ClassDistribution(
            counts=FrozenMapping(counts),
            shares=FrozenMapping(
                {
                    target: (count / total if total else 0.0)
                    for target, count in counts.items()
                }
            ),
        )
    return distributions


def _dataset_checksum(samples: Sequence[XGBoostDatasetSample]) -> str:
    payload = [
        sample.model_dump(mode="json", exclude={"ingestion_audit"})
        for sample in samples
    ]
    return _sha256(payload)


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


xgboost_dataset_builder = XGBoostDatasetBuilder()
