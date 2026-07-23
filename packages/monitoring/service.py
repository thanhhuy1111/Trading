"""Phase 11: metrics recording + the current six-axis readiness snapshot.

`current_readiness` mirrors the same conservative logic the API's `/readiness` endpoint uses
(apps/api/routers/recommendations.py:get_readiness) - both read live from the injected
EvidenceStore rather than caching a stale summary, so neither can drift from the other or from
reality."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from packages.domain.entities import ReadinessStatus
from packages.domain.enums import (
    ArchitectureReadiness,
    EvidenceReadiness,
    LiveReadiness,
    ModelReadiness,
    StrategyReadiness,
)
from packages.evidence.store import EvidenceStore
from packages.monitoring.metrics import ALL_METRIC_NAMES


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: Decimal
    tags: Dict[str, str]
    recorded_at: datetime


class InMemoryMetricsStore:
    def __init__(self) -> None:
        self._samples: List[MetricSample] = []

    def record(self, name: str, value: Decimal, tags: Optional[Dict[str, str]] = None) -> MetricSample:
        sample = MetricSample(name=name, value=value, tags=tags or {}, recorded_at=datetime.now(timezone.utc))
        self._samples.append(sample)
        return sample

    def samples_for(self, name: str) -> List[MetricSample]:
        return [s for s in self._samples if s.name == name]

    def total(self, name: str) -> Decimal:
        return sum((s.value for s in self.samples_for(name)), Decimal("0"))

    def all_samples(self) -> List[MetricSample]:
        return list(self._samples)


class BaselineMonitoringService:
    def __init__(self, evidence_store: EvidenceStore, metrics_store: Optional[InMemoryMetricsStore] = None) -> None:
        self._evidence_store = evidence_store
        self.metrics_store = metrics_store if metrics_store is not None else InMemoryMetricsStore()

    def record_metric(self, name: str, value: Decimal, tags: Optional[Dict[str, str]] = None) -> None:
        if name not in ALL_METRIC_NAMES:
            # Unknown metric names are recorded anyway (an operator adding a new metric
            # shouldn't be blocked by this module), but flagged so drift in the named-metric
            # set is visible rather than silent.
            tags = {**(tags or {}), "unregistered_metric_name": "true"}
        self.metrics_store.record(name, value, tags)

    def current_readiness(self) -> ReadinessStatus:
        records = self._evidence_store.all_records()
        approved_statuses = ("UNIVERSAL_APPROVED", "ASSET_SPECIFIC_APPROVED")
        approved = [r for r in records if r.status.value in approved_statuses]

        strategy_readiness = StrategyReadiness.RESEARCH_ONLY
        evidence_readiness = EvidenceReadiness.NO_APPROVED_STRATEGY
        if not records:
            evidence_readiness = EvidenceReadiness.EMPTY_REGISTRY
        elif any(r.status.value == "UNIVERSAL_APPROVED" for r in approved):
            strategy_readiness = StrategyReadiness.UNIVERSAL_APPROVED
            evidence_readiness = EvidenceReadiness.UNIVERSAL_EVIDENCE
        elif approved:
            strategy_readiness = StrategyReadiness.ASSET_SPECIFIC_APPROVED
            evidence_readiness = EvidenceReadiness.ASSET_SPECIFIC_EVIDENCE

        return ReadinessStatus(
            architecture_readiness=ArchitectureReadiness.READY,
            strategy_readiness=strategy_readiness,
            model_readiness=ModelReadiness.BASELINE,
            evidence_readiness=evidence_readiness,
            shadow_readiness="READY",
            live_readiness=LiveReadiness.DISABLED,
            reason_codes=[],
        )
