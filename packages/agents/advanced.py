from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from threading import RLock
from typing import Dict, Literal, Optional, Protocol, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.common.immutable import FrozenMapping
from packages.experiments.service import CanonicalPayload


class AdvancedSourceKind(str, Enum):
    NEWS = "NEWS"
    ONCHAIN = "ONCHAIN"
    MACRO = "MACRO"
    SENTIMENT = "SENTIMENT"
    MARKET_REGIME = "MARKET_REGIME"


_SOURCE_FIELDS = {
    AdvancedSourceKind.NEWS: frozenset(
        {"headline_hash", "published_at", "relevance_score", "relevance_unit"}
    ),
    AdvancedSourceKind.ONCHAIN: frozenset(
        {"metric_name", "metric_value", "metric_unit", "block_time"}
    ),
    AdvancedSourceKind.MACRO: frozenset(
        {"series_id", "value", "unit", "release_time", "revision"}
    ),
    AdvancedSourceKind.SENTIMENT: frozenset(
        {"score", "unit", "sample_window", "window_end"}
    ),
    AdvancedSourceKind.MARKET_REGIME: frozenset(
        {"regime", "methodology_version", "window_start", "window_end"}
    ),
}

_SOURCE_TIME_FIELD = {
    AdvancedSourceKind.NEWS: "published_at",
    AdvancedSourceKind.ONCHAIN: "block_time",
    AdvancedSourceKind.MACRO: "release_time",
    AdvancedSourceKind.SENTIMENT: "window_end",
    AdvancedSourceKind.MARKET_REGIME: "window_end",
}


class AdvancedAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class DataQuality(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class AdvancedFeatureFlags(BaseModel):
    model_config = ConfigDict(frozen=True)

    news: bool = False
    onchain: bool = False
    macro: bool = False
    sentiment: bool = False
    market_regime: bool = False
    eth: bool = False
    reflection: bool = False
    dynamic_weights: bool = False

    @classmethod
    def from_settings(cls, configured: object) -> "AdvancedFeatureFlags":
        return cls(
            news=bool(getattr(configured, "FEATURE_ADVANCED_NEWS", False)),
            onchain=bool(getattr(configured, "FEATURE_ADVANCED_ONCHAIN", False)),
            macro=bool(getattr(configured, "FEATURE_ADVANCED_MACRO", False)),
            sentiment=bool(getattr(configured, "FEATURE_ADVANCED_SENTIMENT", False)),
            market_regime=bool(getattr(configured, "FEATURE_ADVANCED_REGIME", False)),
            eth=bool(getattr(configured, "FEATURE_ADVANCED_ETH", False)),
            reflection=bool(getattr(configured, "FEATURE_ADVANCED_REFLECTION", False)),
            dynamic_weights=bool(
                getattr(configured, "FEATURE_ADVANCED_DYNAMIC_WEIGHTS", False)
            ),
        )

    def enabled(self, kind: AdvancedSourceKind) -> bool:
        return {
            AdvancedSourceKind.NEWS: self.news,
            AdvancedSourceKind.ONCHAIN: self.onchain,
            AdvancedSourceKind.MACRO: self.macro,
            AdvancedSourceKind.SENTIMENT: self.sentiment,
            AdvancedSourceKind.MARKET_REGIME: self.market_regime,
        }[kind]


class AdvancedSourceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(min_length=1)
    kind: AdvancedSourceKind
    symbol: str
    as_of_time: datetime


class AdvancedSourceObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: AdvancedSourceKind
    provider_id: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    license_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    provenance_uri: str = Field(pattern=r"^https://")
    symbol: str
    observed_at: datetime
    available_at: datetime
    received_at: datetime
    quality: DataQuality
    values: FrozenMapping[str, str]

    @model_validator(mode="after")
    def validate_observation(self) -> "AdvancedSourceObservation":
        if any(
            value.tzinfo is None
            for value in (self.observed_at, self.available_at, self.received_at)
        ):
            raise ValueError("ADVANCED_TIMEZONE_REQUIRED")
        if not self.observed_at <= self.available_at <= self.received_at:
            raise ValueError("ADVANCED_AVAILABILITY_ORDER_INVALID")
        if not self.values:
            raise ValueError("ADVANCED_VALUES_REQUIRED")
        for value in (
            self.provider_id,
            self.provider_version,
            self.license_id,
            self.source_record_id,
            self.symbol,
        ):
            if value != value.strip() or not value:
                raise ValueError("ADVANCED_IDENTIFIER_INVALID")
        if frozenset(self.values) != _SOURCE_FIELDS[self.kind]:
            raise ValueError("ADVANCED_SOURCE_SCHEMA_MISMATCH")
        if any(
            key != key.strip() or value != value.strip() or not value
            for key, value in self.values.items()
        ):
            raise ValueError("ADVANCED_SOURCE_VALUE_INVALID")
        source_time_raw = self.values[_SOURCE_TIME_FIELD[self.kind]]
        try:
            source_time = datetime.fromisoformat(source_time_raw)
        except ValueError as exc:
            raise ValueError("ADVANCED_SOURCE_TIME_INVALID") from exc
        if source_time.tzinfo is None or source_time > self.observed_at:
            raise ValueError("ADVANCED_SOURCE_TIME_INVALID")
        if self.kind == AdvancedSourceKind.NEWS:
            relevance = Decimal(self.values["relevance_score"])
            if self.values["relevance_unit"] != "probability" or not 0 <= relevance <= 1:
                raise ValueError("ADVANCED_NEWS_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.SENTIMENT:
            score = Decimal(self.values["score"])
            if self.values["unit"] != "normalized_score" or not -1 <= score <= 1:
                raise ValueError("ADVANCED_SENTIMENT_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.ONCHAIN:
            allowed_onchain = {
                "active_addresses": "addresses",
                "exchange_netflow": "base_asset",
                "realized_cap": "quote_currency",
            }
            metric_value = Decimal(self.values["metric_value"])
            if (
                self.values["metric_name"] not in allowed_onchain
                or self.values["metric_unit"]
                != allowed_onchain[self.values["metric_name"]]
                or not metric_value.is_finite()
                or (
                    self.values["metric_name"] in {"active_addresses", "realized_cap"}
                    and metric_value < 0
                )
            ):
                raise ValueError("ADVANCED_ONCHAIN_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.MACRO:
            allowed_macro = {
                "CPI": "percent",
                "FED_FUNDS": "percent",
                "DXY": "index",
            }
            macro_value = Decimal(self.values["value"])
            if (
                self.values["series_id"] not in allowed_macro
                or self.values["unit"] != allowed_macro[self.values["series_id"]]
                or self.values["revision"] not in {"initial", "revised"}
                or not macro_value.is_finite()
                or (
                    self.values["series_id"] == "CPI"
                    and not Decimal("-20") <= macro_value <= Decimal("100")
                )
                or (
                    self.values["series_id"] == "FED_FUNDS"
                    and not Decimal("0") <= macro_value <= Decimal("100")
                )
                or (
                    self.values["series_id"] == "DXY"
                    and macro_value <= 0
                )
            ):
                raise ValueError("ADVANCED_MACRO_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.MARKET_REGIME:
            if self.values["regime"] not in {
                "BULL",
                "BEAR",
                "NEUTRAL",
                "HIGH_VOLATILITY",
            }:
                raise ValueError("ADVANCED_REGIME_SCHEMA_INVALID")
            if self.values["methodology_version"] != "regime_v1":
                raise ValueError("ADVANCED_REGIME_SCHEMA_INVALID")
            try:
                window_start = datetime.fromisoformat(self.values["window_start"])
            except ValueError as exc:
                raise ValueError("ADVANCED_REGIME_SCHEMA_INVALID") from exc
            if window_start.tzinfo is None or window_start >= source_time:
                raise ValueError("ADVANCED_REGIME_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.NEWS:
            headline_hash = self.values["headline_hash"]
            if len(headline_hash) != 64 or any(
                character not in "0123456789abcdef" for character in headline_hash
            ):
                raise ValueError("ADVANCED_NEWS_SCHEMA_INVALID")
        if self.kind == AdvancedSourceKind.SENTIMENT:
            if self.values["sample_window"] not in {"15m", "1h", "4h", "1d"}:
                raise ValueError("ADVANCED_SENTIMENT_SCHEMA_INVALID")
        CanonicalPayload.capture(
            {
                "provider_id": self.provider_id,
                "license_id": self.license_id,
                "source_record_id": self.source_record_id,
                "provenance_uri": self.provenance_uri,
                "values": dict(self.values),
            }
        )
        return self


class AdvancedProviderResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    availability: AdvancedAvailability
    observation: Optional[AdvancedSourceObservation] = None
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> "AdvancedProviderResult":
        if self.availability == AdvancedAvailability.AVAILABLE:
            if self.observation is None or self.reason_codes:
                raise ValueError("available advanced result requires one observation")
        elif self.observation is not None or not self.reason_codes:
            raise ValueError("unavailable advanced result requires reasons only")
        return self


class AdvancedSourceProvider(Protocol):
    async def fetch(self, request: AdvancedSourceRequest) -> AdvancedProviderResult: ...


class AdvancedEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(pattern=r"^adv_[0-9a-f]{64}$")
    analysis_id: str
    kind: AdvancedSourceKind
    symbol: str
    provider_id: str
    provider_version: str
    license_id: str
    license_grant_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_retention_days: int = Field(ge=1)
    redistribution_allowed: bool
    source_record_id: str
    provenance_uri: str
    observed_at: datetime
    available_at: datetime
    received_at: datetime
    values: FrozenMapping[str, str]
    schema_version: str = "advanced_evidence_v1"

    @model_validator(mode="after")
    def validate_evidence(self) -> "AdvancedEvidenceRecord":
        if any(
            value.tzinfo is None
            for value in (self.observed_at, self.available_at, self.received_at)
        ):
            raise ValueError("ADVANCED_TIMEZONE_REQUIRED")
        if not self.observed_at <= self.available_at <= self.received_at:
            raise ValueError("ADVANCED_AVAILABILITY_ORDER_INVALID")
        expected_id = self.derive_id(
            analysis_id=self.analysis_id,
            kind=self.kind,
            symbol=self.symbol,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            license_id=self.license_id,
            license_grant_fingerprint=self.license_grant_fingerprint,
            license_retention_days=self.license_retention_days,
            redistribution_allowed=self.redistribution_allowed,
            source_record_id=self.source_record_id,
            provenance_uri=self.provenance_uri,
            observed_at=self.observed_at,
            available_at=self.available_at,
            received_at=self.received_at,
            values=self.values,
        )
        if self.evidence_id != expected_id:
            raise ValueError("ADVANCED_EVIDENCE_ID_MISMATCH")
        AdvancedSourceObservation(
            kind=self.kind,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            license_id=self.license_id,
            source_record_id=self.source_record_id,
            provenance_uri=self.provenance_uri,
            symbol=self.symbol,
            observed_at=self.observed_at,
            available_at=self.available_at,
            received_at=self.received_at,
            quality=DataQuality.HEALTHY,
            values=self.values,
        )
        return self

    @staticmethod
    def derive_id(
        *,
        analysis_id: str,
        kind: AdvancedSourceKind,
        symbol: str,
        provider_id: str,
        provider_version: str,
        license_id: str,
        license_grant_fingerprint: str,
        license_retention_days: int,
        redistribution_allowed: bool,
        source_record_id: str,
        provenance_uri: str,
        observed_at: datetime,
        available_at: datetime,
        received_at: datetime,
        values: FrozenMapping[str, str],
    ) -> str:
        material = "|".join(
            (
                analysis_id,
                kind.value,
                symbol,
                provider_id,
                provider_version,
                license_id,
                license_grant_fingerprint,
                str(license_retention_days),
                str(redistribution_allowed),
                source_record_id,
                provenance_uri,
                observed_at.astimezone(timezone.utc).isoformat(),
                available_at.astimezone(timezone.utc).isoformat(),
                received_at.astimezone(timezone.utc).isoformat(),
                repr(tuple(sorted(values.items()))),
            )
        )
        return "adv_" + sha256(material.encode("utf-8")).hexdigest()


class AdvancedSourceAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    kind: AdvancedSourceKind
    status: AdvancedAvailability
    evidence: Optional[AdvancedEvidenceRecord] = None
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_analysis(self) -> "AdvancedSourceAnalysis":
        if self.status == AdvancedAvailability.AVAILABLE:
            if self.evidence is None or self.reason_codes:
                raise ValueError("available advanced analysis requires evidence")
        elif self.evidence is not None or not self.reason_codes:
            raise ValueError("unavailable advanced analysis requires reasons only")
        return self


class AdvancedEvidenceRegistry:
    def __init__(self, licenses: "SourceLicenseRegistry") -> None:
        self._records: Dict[str, AdvancedEvidenceRecord] = {}
        self._lock = RLock()
        self._licenses = licenses

    def register(self, record: AdvancedEvidenceRecord) -> AdvancedEvidenceRecord:
        record = AdvancedEvidenceRecord.model_validate(record.model_dump())
        if not self._licenses.matches_evidence(record):
            raise ValueError("ADVANCED_EVIDENCE_LICENSE_INVALID")
        with self._lock:
            existing = self._records.get(record.evidence_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("ADVANCED_EVIDENCE_CONFLICT")
                return existing
            self._records[record.evidence_id] = record
            return record

    def get(self, evidence_id: str) -> Optional[AdvancedEvidenceRecord]:
        with self._lock:
            return self._records.get(evidence_id)


class SourceLicenseGrant(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: AdvancedSourceKind
    provider_id: str
    license_id: str
    allowed_domains: Tuple[str, ...]
    research_use_allowed: Literal[True] = True
    retention_days: int = Field(ge=1)
    redistribution_allowed: bool = False

    def fingerprint(self) -> str:
        material = "|".join(
            (
                self.kind.value,
                self.provider_id,
                self.license_id,
                ",".join(sorted(self.allowed_domains)),
                str(self.retention_days),
                str(self.redistribution_allowed),
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()


class SourceLicenseRegistry:
    def __init__(self) -> None:
        self._allowed: Dict[
            Tuple[AdvancedSourceKind, str, str],
            SourceLicenseGrant,
        ] = {}
        self._lock = RLock()

    def allow(
        self,
        kind: AdvancedSourceKind,
        provider_id: str,
        license_id: str,
        *,
        allowed_domains: Tuple[str, ...],
        retention_days: int,
        redistribution_allowed: bool = False,
    ) -> None:
        if (
            not provider_id.strip()
            or not license_id.strip()
            or not allowed_domains
            or any(not domain.strip() for domain in allowed_domains)
        ):
            raise ValueError("ADVANCED_LICENSE_IDENTIFIER_INVALID")
        grant = SourceLicenseGrant(
            kind=kind,
            provider_id=provider_id,
            license_id=license_id,
            allowed_domains=allowed_domains,
            retention_days=retention_days,
            redistribution_allowed=redistribution_allowed,
        )
        key = (kind, provider_id, license_id)
        with self._lock:
            existing = self._allowed.get(key)
            if existing is not None and existing != grant:
                raise ValueError("ADVANCED_LICENSE_GRANT_CONFLICT")
            self._allowed[key] = grant

    def authorize(
        self,
        observation: AdvancedSourceObservation,
    ) -> Optional[SourceLicenseGrant]:
        with self._lock:
            grant = self._allowed.get(
                (
                    observation.kind,
                    observation.provider_id,
                    observation.license_id,
                )
            )
        if grant is None:
            return None
        hostname = urlparse(observation.provenance_uri).hostname
        return grant if hostname in grant.allowed_domains else None

    def matches_evidence(self, record: AdvancedEvidenceRecord) -> bool:
        observation = AdvancedSourceObservation(
            kind=record.kind,
            provider_id=record.provider_id,
            provider_version=record.provider_version,
            license_id=record.license_id,
            source_record_id=record.source_record_id,
            provenance_uri=record.provenance_uri,
            symbol=record.symbol,
            observed_at=record.observed_at,
            available_at=record.available_at,
            received_at=record.received_at,
            quality=DataQuality.HEALTHY,
            values=record.values,
        )
        grant = self.authorize(observation)
        return (
            grant is not None
            and record.license_grant_fingerprint == grant.fingerprint()
            and record.license_retention_days == grant.retention_days
            and record.redistribution_allowed == grant.redistribution_allowed
        )


class AdvancedSourceService:
    def __init__(
        self,
        *,
        flags: AdvancedFeatureFlags,
        providers: FrozenMapping[AdvancedSourceKind, AdvancedSourceProvider],
        evidence: AdvancedEvidenceRegistry,
        licenses: SourceLicenseRegistry,
        provider_timeout_seconds: float = 5.0,
    ) -> None:
        self.flags = flags
        self.providers = providers
        self.evidence = evidence
        self.licenses = licenses
        if provider_timeout_seconds <= 0:
            raise ValueError("ADVANCED_PROVIDER_TIMEOUT_INVALID")
        self.provider_timeout_seconds = provider_timeout_seconds

    async def analyze(self, request: AdvancedSourceRequest) -> AdvancedSourceAnalysis:
        if request.as_of_time.tzinfo is None:
            return self._unavailable(request, "ADVANCED_AS_OF_INVALID")
        if not self.flags.enabled(request.kind):
            return self._unavailable(request, "ADVANCED_FEATURE_DISABLED")
        provider = self.providers.get(request.kind)
        if provider is None:
            return self._unavailable(request, "ADVANCED_PROVIDER_NOT_CONFIGURED")
        try:
            raw_result = await asyncio.wait_for(
                provider.fetch(request),
                timeout=self.provider_timeout_seconds,
            )
            payload = (
                raw_result.model_dump()
                if isinstance(raw_result, BaseModel)
                else raw_result
            )
            result = AdvancedProviderResult.model_validate(payload)
        except asyncio.TimeoutError:
            return self._unavailable(request, "ADVANCED_PROVIDER_TIMEOUT")
        except Exception:
            return self._unavailable(request, "ADVANCED_PROVIDER_ERROR")
        if result.availability != AdvancedAvailability.AVAILABLE:
            return self._unavailable(
                request,
                *(result.reason_codes or ("ADVANCED_PROVIDER_UNAVAILABLE",)),
            )
        observation = result.observation
        if observation is None:
            return self._unavailable(request, "ADVANCED_PROVIDER_SCHEMA_INVALID")
        if observation.kind != request.kind or observation.symbol != request.symbol:
            return self._unavailable(request, "ADVANCED_SOURCE_SCOPE_MISMATCH")
        if (
            observation.available_at > request.as_of_time
            or observation.received_at > request.as_of_time
        ):
            return self._unavailable(request, "ADVANCED_LOOKAHEAD_REJECTED")
        if observation.quality != DataQuality.HEALTHY:
            return self._unavailable(request, "ADVANCED_DATA_QUALITY_REJECTED")
        grant = self.licenses.authorize(observation)
        if grant is None:
            return self._unavailable(request, "ADVANCED_LICENSE_REJECTED")
        record = AdvancedEvidenceRecord(
            evidence_id=AdvancedEvidenceRecord.derive_id(
                analysis_id=request.analysis_id,
                kind=request.kind,
                symbol=request.symbol,
                provider_id=observation.provider_id,
                provider_version=observation.provider_version,
                license_id=observation.license_id,
                license_grant_fingerprint=grant.fingerprint(),
                license_retention_days=grant.retention_days,
                redistribution_allowed=grant.redistribution_allowed,
                source_record_id=observation.source_record_id,
                provenance_uri=observation.provenance_uri,
                observed_at=observation.observed_at,
                available_at=observation.available_at,
                received_at=observation.received_at,
                values=observation.values,
            ),
            analysis_id=request.analysis_id,
            kind=request.kind,
            symbol=request.symbol,
            provider_id=observation.provider_id,
            provider_version=observation.provider_version,
            license_id=observation.license_id,
            license_grant_fingerprint=grant.fingerprint(),
            license_retention_days=grant.retention_days,
            redistribution_allowed=grant.redistribution_allowed,
            source_record_id=observation.source_record_id,
            provenance_uri=observation.provenance_uri,
            observed_at=observation.observed_at,
            available_at=observation.available_at,
            received_at=observation.received_at,
            values=observation.values,
        )
        self.evidence.register(record)
        return AdvancedSourceAnalysis(
            analysis_id=request.analysis_id,
            kind=request.kind,
            status=AdvancedAvailability.AVAILABLE,
            evidence=record,
        )

    @staticmethod
    def _unavailable(
        request: AdvancedSourceRequest,
        *reasons: str,
    ) -> AdvancedSourceAnalysis:
        return AdvancedSourceAnalysis(
            analysis_id=request.analysis_id,
            kind=request.kind,
            status=AdvancedAvailability.UNAVAILABLE,
            reason_codes=tuple(reasons),
        )


class AdvancedResearchBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    symbol: str
    as_of_time: datetime
    assessments: Tuple[AdvancedSourceAnalysis, ...]
    research_only: Literal[True] = True
    production_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_bundle(self) -> "AdvancedResearchBundle":
        expected = tuple(AdvancedSourceKind)
        if tuple(item.kind for item in self.assessments) != expected:
            raise ValueError("ADVANCED_AGENT_SET_INVALID")
        if any(item.analysis_id != self.analysis_id for item in self.assessments):
            raise ValueError("ADVANCED_ANALYSIS_ID_MISMATCH")
        return self


class AdvancedAgentCoordinator:
    """Runs the complete research-only advanced agent set without production authority."""

    def __init__(self, service: AdvancedSourceService) -> None:
        self.service = service

    async def run(
        self,
        *,
        analysis_id: str,
        symbol: str,
        as_of_time: datetime,
    ) -> AdvancedResearchBundle:
        assessments = []
        for kind in AdvancedSourceKind:
            assessments.append(
                await self.service.analyze(
                    AdvancedSourceRequest(
                        analysis_id=analysis_id,
                        kind=kind,
                        symbol=symbol,
                        as_of_time=as_of_time,
                    )
                )
            )
        return AdvancedResearchBundle(
            analysis_id=analysis_id,
            symbol=symbol,
            as_of_time=as_of_time,
            assessments=tuple(assessments),
        )


class AssetModelBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: Literal["BTCUSDT", "ETHUSDT"]
    model_id: str
    model_version: str
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_symbol: Literal["BTCUSDT", "ETHUSDT"]
    timeframe: str
    feature_schema_version: str
    registry_status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    research_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_asset_scope(self) -> "AssetModelBinding":
        if self.training_symbol != self.symbol:
            raise ValueError("ASSET_MODEL_TRAINING_SYMBOL_MISMATCH")
        return self


class AssetModelBindingRegistry:
    def __init__(self, flags: Optional[AdvancedFeatureFlags] = None) -> None:
        self._bindings: Dict[str, AssetModelBinding] = {}
        self._flags = flags or AdvancedFeatureFlags()

    def register(self, binding: AssetModelBinding) -> AssetModelBinding:
        if binding.symbol in self._bindings:
            raise ValueError("ASSET_MODEL_BINDING_EXISTS")
        if any(
            (existing.model_id, existing.model_version)
            == (binding.model_id, binding.model_version)
            for existing in self._bindings.values()
        ):
            raise ValueError("ASSET_MODEL_CROSS_SYMBOL_REUSE")
        if any(
            existing.artifact_checksum == binding.artifact_checksum
            for existing in self._bindings.values()
        ):
            raise ValueError("ASSET_MODEL_ARTIFACT_CROSS_SYMBOL_REUSE")
        self._bindings[binding.symbol] = binding
        return binding

    def resolve(self, symbol: str) -> Optional[AssetModelBinding]:
        if symbol == "ETHUSDT" and not self._flags.eth:
            return None
        return self._bindings.get(symbol)


class ReflectionProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    analysis_ids: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    proposed_changes: Tuple[str, ...]
    research_only: Literal[True] = True
    production_prompt_mutation: Literal[False] = False
    promotion_status: Literal["REQUIRES_APPROVAL"] = "REQUIRES_APPROVAL"

    @model_validator(mode="after")
    def validate_proposal(self) -> "ReflectionProposal":
        if not self.analysis_ids or not self.evidence_ids or not self.proposed_changes:
            raise ValueError("REFLECTION_PROPOSAL_EVIDENCE_REQUIRED")
        return self


class DynamicWeightProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    analysis_ids: Tuple[str, ...]
    weights: FrozenMapping[str, Decimal]
    evidence_ids: Tuple[str, ...]
    research_only: Literal[True] = True
    production_weight_mutation: Literal[False] = False
    promotion_status: Literal["REQUIRES_APPROVAL"] = "REQUIRES_APPROVAL"

    @model_validator(mode="after")
    def validate_weights(self) -> "DynamicWeightProposal":
        if not self.weights or any(value < 0 for value in self.weights.values()):
            raise ValueError("DYNAMIC_WEIGHT_INVALID")
        if sum(self.weights.values(), Decimal("0")) != Decimal("1"):
            raise ValueError("DYNAMIC_WEIGHT_SUM_INVALID")
        if not self.analysis_ids or not self.evidence_ids:
            raise ValueError("DYNAMIC_WEIGHT_EVIDENCE_REQUIRED")
        return self


class AdvancedResearchProposalGate:
    def __init__(
        self,
        flags: AdvancedFeatureFlags,
        evidence: AdvancedEvidenceRegistry,
    ) -> None:
        self.flags = flags
        self.evidence = evidence

    def _validate_evidence(
        self,
        evidence_ids: Tuple[str, ...],
        analysis_ids: Tuple[str, ...],
    ) -> None:
        for evidence_id in evidence_ids:
            record = self.evidence.get(evidence_id)
            if record is None:
                raise ValueError("ADVANCED_PROPOSAL_EVIDENCE_NOT_FOUND")
            if record.analysis_id not in analysis_ids:
                raise ValueError("ADVANCED_PROPOSAL_ANALYSIS_MISMATCH")
        resolved_analysis_ids = {
            self.evidence.get(evidence_id).analysis_id  # type: ignore[union-attr]
            for evidence_id in evidence_ids
        }
        if resolved_analysis_ids != set(analysis_ids):
            raise ValueError("ADVANCED_PROPOSAL_ANALYSIS_SCOPE_UNSUPPORTED")

    def reflection(self, proposal: ReflectionProposal) -> ReflectionProposal:
        if not self.flags.reflection:
            raise ValueError("ADVANCED_REFLECTION_DISABLED")
        self._validate_evidence(proposal.evidence_ids, proposal.analysis_ids)
        return proposal

    def dynamic_weights(self, proposal: DynamicWeightProposal) -> DynamicWeightProposal:
        if not self.flags.dynamic_weights:
            raise ValueError("ADVANCED_DYNAMIC_WEIGHTS_DISABLED")
        self._validate_evidence(proposal.evidence_ids, proposal.analysis_ids)
        return proposal
