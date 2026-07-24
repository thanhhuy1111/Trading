from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.common.immutable import FrozenMapping
from packages.telemetry.redaction import SENSITIVE_KEYS, SensitiveDataRedactor

_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S{12,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("EXPERIMENT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat()


def _canonical_horizon(value: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]*(m|h|d)", value):
        raise ValueError("EXPERIMENT_HORIZON_INVALID")
    quantity = int(value[:-1])
    unit = value[-1]
    minutes = quantity * {"m": 1, "h": 60, "d": 1440}[unit]
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("EXPERIMENT_NONFINITE_VALUE")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("EXPERIMENT_NONFINITE_VALUE")
        return {"$decimal": format(value, "f")}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("EXPERIMENT_TIMEZONE_REQUIRED")
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if isinstance(value, BaseModel):
        return _normalize_json(value.model_dump(mode="json"))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("EXPERIMENT_JSON_KEYS_MUST_BE_STRINGS")
        return {key: _normalize_json(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    raise ValueError(f"EXPERIMENT_UNSUPPORTED_JSON_TYPE:{type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(
        _normalize_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(secret in normalized for secret in SENSITIVE_KEYS):
                return True
            if _contains_secret(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    elif isinstance(value, str):
        return (
            SensitiveDataRedactor.redact_string(value) != value
            or any(pattern.search(value) is not None for pattern in _SECRET_VALUE_PATTERNS)
        )
    return False


class CanonicalPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_json: str
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_payload(self) -> "CanonicalPayload":
        try:
            value = json.loads(self.canonical_json)
        except json.JSONDecodeError as exc:
            raise ValueError("EXPERIMENT_PAYLOAD_INVALID_JSON") from exc
        if _canonical(value) != self.canonical_json:
            raise ValueError("EXPERIMENT_PAYLOAD_NOT_CANONICAL")
        if _contains_secret(value):
            raise ValueError("EXPERIMENT_SECRET_MATERIAL_REJECTED")
        expected = sha256(self.canonical_json.encode("utf-8")).hexdigest()
        if self.checksum != expected:
            raise ValueError("EXPERIMENT_PAYLOAD_CHECKSUM_MISMATCH")
        return self

    @classmethod
    def capture(cls, value: Any) -> "CanonicalPayload":
        if _contains_secret(value):
            raise ValueError("EXPERIMENT_SECRET_MATERIAL_REJECTED")
        canonical = _canonical(value)
        return cls(
            canonical_json=canonical,
            checksum=sha256(canonical.encode("utf-8")).hexdigest(),
        )


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    retention_days: int = Field(default=365, ge=1)
    deletion_mode: str = Field(default="MANUAL_AUDITED", pattern=r"^MANUAL_AUDITED$")
    archive_before_delete: bool = True
    policy_version: str = "experiment_retention_v1"


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(pattern=r"^exp_[0-9a-f]{64}$")
    analysis_id: str = Field(min_length=1)
    sequence_number: int = Field(ge=1)
    symbol: str
    timeframe: str
    as_of_time: datetime
    recorded_at: datetime
    raw_inputs: CanonicalPayload
    normalized_inputs: CanonicalPayload
    feature_snapshot: CanonicalPayload
    evidence_snapshot: CanonicalPayload
    model_versions: FrozenMapping[str, str]
    prompt_versions: FrozenMapping[str, str]
    agent_outputs: CanonicalPayload
    debate_transcript: CanonicalPayload
    verification_result: CanonicalPayload
    risk_result: CanonicalPayload
    manager_result: CanonicalPayload
    agent_disagreement: Optional[bool] = None
    verification_rejected: bool
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    cost_amount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    cost_currency: Optional[str] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_codes: Tuple[str, ...] = ()
    expected_field_count: int = Field(ge=1)
    missing_field_count: int = Field(ge=0)
    data_quality: CanonicalPayload
    schema_version: str = "experiment_record_v1"

    @model_validator(mode="after")
    def validate_record(self) -> "ExperimentRecord":
        for value in (self.as_of_time, self.recorded_at):
            if value.tzinfo is None:
                raise ValueError("EXPERIMENT_TIMEZONE_REQUIRED")
        if self.recorded_at < self.as_of_time:
            raise ValueError("EXPERIMENT_RECORDED_BEFORE_AS_OF")
        if self.missing_field_count > self.expected_field_count:
            raise ValueError("EXPERIMENT_MISSING_FIELD_COUNT_INVALID")
        if (self.cost_amount is None) != (self.cost_currency is None):
            raise ValueError("EXPERIMENT_COST_AMOUNT_CURRENCY_REQUIRED_TOGETHER")
        if _contains_secret(dict(self.model_versions)) or _contains_secret(
            dict(self.prompt_versions)
        ):
            raise ValueError("EXPERIMENT_SECRET_MATERIAL_REJECTED")
        if _contains_secret(
            {
                "analysis_id": self.analysis_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "error_codes": list(self.error_codes),
                "cost_currency": self.cost_currency,
            }
        ):
            raise ValueError("EXPERIMENT_SECRET_MATERIAL_REJECTED")
        expected_id = self.derive_id(
            analysis_id=self.analysis_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            as_of_time=self.as_of_time,
            raw_checksum=self.raw_inputs.checksum,
            normalized_checksum=self.normalized_inputs.checksum,
            feature_checksum=self.feature_snapshot.checksum,
            evidence_checksum=self.evidence_snapshot.checksum,
            model_versions=dict(self.model_versions),
            prompt_versions=dict(self.prompt_versions),
        )
        if self.experiment_id != expected_id:
            raise ValueError("EXPERIMENT_ID_MISMATCH")
        return self

    @staticmethod
    def derive_id(
        *,
        analysis_id: str,
        symbol: str,
        timeframe: str,
        as_of_time: datetime,
        raw_checksum: str,
        normalized_checksum: str,
        feature_checksum: str,
        evidence_checksum: str,
        model_versions: Dict[str, str],
        prompt_versions: Dict[str, str],
    ) -> str:
        material = _canonical(
            {
                "analysis_id": analysis_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "as_of_time": _utc_iso(as_of_time),
                "raw_checksum": raw_checksum,
                "normalized_checksum": normalized_checksum,
                "feature_checksum": feature_checksum,
                "evidence_checksum": evidence_checksum,
                "model_versions": model_versions,
                "prompt_versions": prompt_versions,
            }
        )
        return "exp_" + sha256(material.encode("utf-8")).hexdigest()


class ExperimentOutcomeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(pattern=r"^out_[0-9a-f]{64}$")
    experiment_id: str = Field(pattern=r"^exp_[0-9a-f]{64}$")
    sequence_number: int = Field(ge=1)
    horizon: str = Field(pattern=r"^[1-9][0-9]*(m|h|d)$")
    outcome_available_at: datetime
    observed_at: datetime
    actual_market_outcome: CanonicalPayload
    prediction_correct: Optional[bool] = None
    simulated_pnl: Optional[Decimal] = None
    pnl_currency: Optional[str] = None
    simulated_return: Optional[Decimal] = None
    drawdown_pct: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    schema_version: str = "experiment_outcome_v1"

    @field_validator("horizon", mode="before")
    @classmethod
    def normalize_horizon(cls, value: str) -> str:
        return _canonical_horizon(value)

    @model_validator(mode="after")
    def validate_event(self) -> "ExperimentOutcomeEvent":
        if self.outcome_available_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("EXPERIMENT_TIMEZONE_REQUIRED")
        if self.observed_at < self.outcome_available_at:
            raise ValueError("EXPERIMENT_OUTCOME_OBSERVED_EARLY")
        if (self.simulated_pnl is None) != (self.pnl_currency is None):
            raise ValueError("EXPERIMENT_PNL_CURRENCY_REQUIRED_TOGETHER")
        if _contains_secret(
            {
                "horizon": self.horizon,
                "pnl_currency": self.pnl_currency,
            }
        ):
            raise ValueError("EXPERIMENT_SECRET_MATERIAL_REJECTED")
        expected = self.derive_id(
            self.experiment_id,
            self.horizon,
            self.outcome_available_at,
            self.actual_market_outcome.checksum,
        )
        if self.event_id != expected:
            raise ValueError("EXPERIMENT_OUTCOME_ID_MISMATCH")
        return self

    @staticmethod
    def derive_id(
        experiment_id: str,
        horizon: str,
        outcome_available_at: datetime,
        outcome_checksum: str,
    ) -> str:
        material = _canonical(
            {
                "experiment_id": experiment_id,
                "horizon": _canonical_horizon(horizon),
                "outcome_available_at": _utc_iso(outcome_available_at),
                "outcome_checksum": outcome_checksum,
            }
        )
        return "out_" + sha256(material.encode("utf-8")).hexdigest()

    def horizon_delta(self) -> timedelta:
        quantity = int(self.horizon[:-1])
        unit = self.horizon[-1]
        if unit == "m":
            return timedelta(minutes=quantity)
        if unit == "h":
            return timedelta(hours=quantity)
        return timedelta(days=quantity)


class ExperimentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_count: int = Field(ge=0)
    horizon: str = Field(pattern=r"^[1-9][0-9]*(m|h|d)$")
    evaluated_prediction_count: int = Field(ge=0)
    correct_prediction_count: int = Field(ge=0)
    prediction_accuracy: Optional[Decimal] = None
    pnl_observation_count: int = Field(ge=0)
    total_simulated_pnl: Optional[Decimal] = None
    pnl_currency: Optional[str] = None
    simulated_return_observation_count: int = Field(ge=0)
    simulated_win_rate: Optional[Decimal] = None
    drawdown_observation_count: int = Field(ge=0)
    maximum_observed_drawdown_pct: Optional[Decimal] = None
    disagreement_observation_count: int = Field(ge=0)
    agent_disagreement_rate: Optional[Decimal] = None
    verification_observation_count: int = Field(ge=0)
    verification_rejection_rate: Optional[Decimal] = None
    cost_observation_count: int = Field(ge=0)
    average_cost_per_analysis: Optional[Decimal] = None
    cost_currency: Optional[str] = None
    latency_observation_count: int = Field(ge=0)
    latency_p50_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    missing_data_rate: Optional[Decimal] = None
    schema_version: str = "experiment_report_v1"


class ExperimentStore:
    """Thread-safe append-only store with conflict detection and deterministic export."""

    def __init__(self, retention_policy: Optional[RetentionPolicy] = None) -> None:
        self.retention_policy = retention_policy or RetentionPolicy()
        self._records: Dict[str, ExperimentRecord] = {}
        self._order: list[str] = []
        self._outcomes: Dict[str, ExperimentOutcomeEvent] = {}
        self._outcome_order: list[str] = []
        self._outcome_keys: Dict[Tuple[str, str], str] = {}
        self._lock = RLock()

    def append(self, record: ExperimentRecord) -> ExperimentRecord:
        record = ExperimentRecord.model_validate(record.model_dump())
        with self._lock:
            existing = self._records.get(record.experiment_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("EXPERIMENT_APPEND_CONFLICT")
                return existing
            expected_sequence = len(self._order) + 1
            if record.sequence_number != expected_sequence:
                raise ValueError("EXPERIMENT_SEQUENCE_CONFLICT")
            self._records[record.experiment_id] = record
            self._order.append(record.experiment_id)
            return record

    def append_outcome(self, event: ExperimentOutcomeEvent) -> ExperimentOutcomeEvent:
        event = ExperimentOutcomeEvent.model_validate(event.model_dump())
        with self._lock:
            record = self._records.get(event.experiment_id)
            if record is None:
                raise ValueError("EXPERIMENT_OUTCOME_PARENT_MISSING")
            if event.outcome_available_at < record.as_of_time + event.horizon_delta():
                raise ValueError("EXPERIMENT_OUTCOME_LOOKAHEAD")
            if event.observed_at < record.recorded_at:
                raise ValueError("EXPERIMENT_OUTCOME_OBSERVED_BEFORE_RECORD")
            existing = self._outcomes.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ValueError("EXPERIMENT_OUTCOME_CONFLICT")
                return existing
            key = (event.experiment_id, event.horizon)
            if key in self._outcome_keys:
                raise ValueError("EXPERIMENT_OUTCOME_CONFLICT")
            if event.sequence_number != len(self._outcome_order) + 1:
                raise ValueError("EXPERIMENT_OUTCOME_SEQUENCE_CONFLICT")
            self._outcomes[event.event_id] = event
            self._outcome_order.append(event.event_id)
            self._outcome_keys[key] = event.event_id
            return event

    def records(self) -> Tuple[ExperimentRecord, ...]:
        with self._lock:
            return tuple(self._records[item] for item in self._order)

    def outcomes(self) -> Tuple[ExperimentOutcomeEvent, ...]:
        with self._lock:
            return tuple(self._outcomes[item] for item in self._outcome_order)

    def export_jsonl(self, destination: Path) -> str:
        with self._lock:
            if destination.exists():
                raise FileExistsError("EXPERIMENT_EXPORT_EXISTS")
            rows = [
                _canonical(
                    {
                        "record_type": "MANIFEST",
                        "payload": {
                            "experiment_schema": "experiment_record_v1",
                            "outcome_schema": "experiment_outcome_v1",
                            "retention_policy": self.retention_policy.model_dump(mode="json"),
                            "experiment_count": len(self._order),
                            "outcome_count": len(self._outcome_order),
                        },
                    }
                )
            ]
            rows.extend(
                _canonical(
                    {
                        "record_type": "EXPERIMENT",
                        "payload": self._records[item].model_dump(mode="json"),
                    }
                )
                for item in self._order
            )
            rows.extend(
                _canonical(
                    {
                        "record_type": "OUTCOME",
                        "payload": self._outcomes[item].model_dump(mode="json"),
                    }
                )
                for item in self._outcome_order
            )
            payload = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        fd, temp_name = tempfile.mkstemp(prefix=".experiment-", dir=destination.parent)
        checksum = sha256(payload).hexdigest()
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # Atomic no-clobber publication. A hard link fails with EEXIST if another
            # process wins after the initial check, unlike os.replace which overwrites.
            os.link(temp_name, destination)
            os.unlink(temp_name)
            try:
                os.fsync(directory_fd)
            except OSError as exc:
                raise RuntimeError(
                    "EXPERIMENT_EXPORT_PUBLISHED_DURABILITY_UNCERTAIN:"
                    f"{destination}:{checksum}"
                ) from exc
        finally:
            os.close(directory_fd)
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return checksum

    def report(self, horizon: str) -> ExperimentReport:
        try:
            horizon = _canonical_horizon(horizon)
        except ValueError as exc:
            raise ValueError("EXPERIMENT_REPORT_HORIZON_INVALID") from exc
        with self._lock:
            records = tuple(self._records[item] for item in self._order)
            outcomes = tuple(
                self._outcomes[item]
                for item in self._outcome_order
                if self._outcomes[item].horizon == horizon
            )
        return build_experiment_report(records, outcomes, horizon=horizon)

    def retention_candidates(self, as_of_time: datetime) -> "RetentionBundle":
        if as_of_time.tzinfo is None:
            raise ValueError("EXPERIMENT_TIMEZONE_REQUIRED")
        with self._lock:
            cutoff = as_of_time - timedelta(days=self.retention_policy.retention_days)
            experiment_ids = tuple(
                item
                for item in self._order
                if self._records[item].recorded_at <= cutoff
            )
            selected = set(experiment_ids)
            outcome_ids = tuple(
                item
                for item in self._outcome_order
                if self._outcomes[item].experiment_id in selected
            )
            return RetentionBundle(
                as_of_time=as_of_time,
                cutoff_time=cutoff,
                policy_version=self.retention_policy.policy_version,
                experiment_ids=experiment_ids,
                outcome_event_ids=outcome_ids,
                archive_before_delete=self.retention_policy.archive_before_delete,
            )


class RetentionBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of_time: datetime
    cutoff_time: datetime
    policy_version: str
    experiment_ids: Tuple[str, ...]
    outcome_event_ids: Tuple[str, ...]
    archive_before_delete: bool


def _nearest_rank(values: Iterable[float], percentile: Decimal) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, int((Decimal(len(ordered)) * percentile).to_integral_value(rounding="ROUND_CEILING")))
    return ordered[rank - 1]


def build_experiment_report(
    records: Tuple[ExperimentRecord, ...],
    outcomes: Tuple[ExperimentOutcomeEvent, ...],
    *,
    horizon: str,
) -> ExperimentReport:
    evaluated = [event for event in outcomes if event.prediction_correct is not None]
    correct = sum(event.prediction_correct is True for event in evaluated)
    pnl_events = [event for event in outcomes if event.simulated_pnl is not None]
    pnl_currencies = {event.pnl_currency for event in pnl_events}
    comparable_pnl = len(pnl_currencies) == 1 and bool(pnl_events)
    pnl = [event.simulated_pnl for event in pnl_events if event.simulated_pnl is not None]
    returns = [event.simulated_return for event in outcomes if event.simulated_return is not None]
    drawdowns = [event.drawdown_pct for event in outcomes if event.drawdown_pct is not None]
    disagreement = [record.agent_disagreement for record in records if record.agent_disagreement is not None]
    verification = [record.verification_rejected for record in records]
    costs = [record for record in records if record.cost_amount is not None]
    cost_currencies = {record.cost_currency for record in costs}
    latencies = [record.latency_ms for record in records if record.latency_ms is not None]
    expected = sum(record.expected_field_count for record in records)
    missing = sum(record.missing_field_count for record in records)
    cost_is_comparable = (
        len(cost_currencies) == 1
        and bool(costs)
        and len(costs) == len(records)
    )
    return ExperimentReport(
        experiment_count=len(records),
        horizon=horizon,
        evaluated_prediction_count=len(evaluated),
        correct_prediction_count=correct,
        prediction_accuracy=(
            Decimal(correct) / Decimal(len(evaluated)) if evaluated else None
        ),
        pnl_observation_count=len(pnl),
        total_simulated_pnl=sum(pnl, Decimal("0")) if comparable_pnl else None,
        pnl_currency=next(iter(pnl_currencies)) if comparable_pnl else None,
        simulated_win_rate=(
            Decimal(sum(value > Decimal("0") for value in returns)) / Decimal(len(returns))
            if returns
            else None
        ),
        simulated_return_observation_count=len(returns),
        drawdown_observation_count=len(drawdowns),
        maximum_observed_drawdown_pct=max(drawdowns) if drawdowns else None,
        disagreement_observation_count=len(disagreement),
        agent_disagreement_rate=(
            Decimal(sum(value is True for value in disagreement)) / Decimal(len(disagreement))
            if disagreement
            else None
        ),
        verification_rejection_rate=(
            Decimal(sum(verification)) / Decimal(len(verification)) if verification else None
        ),
        verification_observation_count=len(verification),
        cost_observation_count=len(costs),
        average_cost_per_analysis=(
            sum((record.cost_amount for record in costs if record.cost_amount is not None), Decimal("0"))
            / Decimal(len(costs))
            if cost_is_comparable
            else None
        ),
        cost_currency=next(iter(cost_currencies)) if cost_is_comparable else None,
        latency_observation_count=len(latencies),
        latency_p50_ms=_nearest_rank(latencies, Decimal("0.50")),
        latency_p95_ms=_nearest_rank(latencies, Decimal("0.95")),
        missing_data_rate=Decimal(missing) / Decimal(expected) if expected else None,
    )
