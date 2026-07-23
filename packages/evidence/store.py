"""In-memory exact-match evidence registry.

`lookup` performs plain dict equality on the full EvidenceKey tuple — nothing here does
prefix matching, "closest" matching, or falls back across symbol/timeframe/model_version. If a
key isn't registered exactly as asked, the answer is "no evidence", never "here's the nearest
thing we have."
"""

from datetime import datetime
from typing import Dict, List, Optional

from packages.evidence.audit import (
    EVIDENCE_CREATED,
    EVIDENCE_DEGRADED,
    EVIDENCE_DISABLED,
    EVIDENCE_STALED,
    EVIDENCE_UPDATED,
    LOOKUP_REJECTED,
    EvidenceAuditLog,
    evidence_audit_log,
)
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus


def _key_summary(key: EvidenceKey) -> str:
    return f"{key.strategy_name}:{key.strategy_version}:{key.symbol}:{key.timeframe}:{key.config_hash[:12]}"


class EvidenceStore:
    def __init__(self, audit_log: Optional[EvidenceAuditLog] = None) -> None:
        self._records: Dict[EvidenceKey, EvidenceRecord] = {}
        self._audit_log = audit_log if audit_log is not None else evidence_audit_log

    def register(self, record: EvidenceRecord) -> None:
        existed = record.key in self._records
        self._records[record.key] = record
        self._audit_log.record(
            EVIDENCE_UPDATED if existed else EVIDENCE_CREATED,
            _key_summary(record.key),
            {"status": record.status.value},
        )
        if record.status == EvidenceStatus.DEGRADED:
            self._audit_log.record(EVIDENCE_DEGRADED, _key_summary(record.key))
        elif record.status == EvidenceStatus.DISABLED:
            self._audit_log.record(EVIDENCE_DISABLED, _key_summary(record.key))

    def lookup(self, key: EvidenceKey, as_of: Optional[datetime] = None) -> Optional[EvidenceRecord]:
        """Exact match only. Returns None if this exact (strategy_name, strategy_version,
        symbol, timeframe, model_type, model_version, feature_version, label_version,
        dataset_checksum, gate_version, config_hash, code_commit) tuple was never registered —
        callers must treat that identically to REJECTED for trading-decision purposes (i.e.
        "no usable evidence"), never substitute a different key's record."""
        record = self._records.get(key)
        if record is None:
            return None
        approved_statuses = (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED)
        if record.status in approved_statuses and record.is_stale(as_of):
            # Return a STALE view rather than the stored APPROVED status — staleness is a
            # function of "now", not a stored field that needs a separate write path.
            self._audit_log.record(EVIDENCE_STALED, _key_summary(key))
            return record.model_copy(update={"status": EvidenceStatus.STALE})
        return record

    def lookup_with_result(self, key: EvidenceKey, as_of: Optional[datetime] = None):
        """Phase 5: typed MATCH/MISMATCH/MISSING/STALE/DISABLED classification (Section 5),
        with every non-MATCH outcome recorded to the audit log as `lookup_rejected` — a
        rejected lookup is exactly as auditable as a granted one."""
        from packages.domain.enums import EvidenceLookupResult
        from packages.ports.interfaces import EvidenceLookupOutcome

        record = self.lookup(key, as_of)
        if record is None:
            # Distinguish "nothing at all for this symbol/timeframe/strategy" (MISSING) from
            # "we have evidence for this strategy_name+symbol+timeframe, but not for this
            # exact model/config/feature/label/dataset/gate/commit combination" (MISMATCH) —
            # the latter is the case Section 5's exact-match rule exists to catch (e.g. a
            # caller silently reusing an old model_version's evidence).
            near_misses = [
                k for k in self._records
                if k.strategy_name == key.strategy_name and k.symbol == key.symbol and k.timeframe == key.timeframe
            ]
            if near_misses:
                self._audit_log.record(LOOKUP_REJECTED, _key_summary(key), {"result": "MISMATCH"})
                return EvidenceLookupOutcome(
                    result=EvidenceLookupResult.MISMATCH, record=None,
                    reason_codes=["EVIDENCE_EXISTS_FOR_DIFFERENT_MODEL_OR_CONFIG_OR_VERSION"],
                )
            self._audit_log.record(LOOKUP_REJECTED, _key_summary(key), {"result": "MISSING"})
            return EvidenceLookupOutcome(
                result=EvidenceLookupResult.MISSING, record=None, reason_codes=["EVIDENCE_NOT_FOUND"],
            )
        if record.status == EvidenceStatus.STALE:
            self._audit_log.record(LOOKUP_REJECTED, _key_summary(key), {"result": "STALE"})
            return EvidenceLookupOutcome(
                result=EvidenceLookupResult.STALE, record=record, reason_codes=["EVIDENCE_STALE"],
            )
        if record.status == EvidenceStatus.DISABLED:
            self._audit_log.record(LOOKUP_REJECTED, _key_summary(key), {"result": "DISABLED"})
            return EvidenceLookupOutcome(
                result=EvidenceLookupResult.DISABLED, record=record, reason_codes=["EVIDENCE_DISABLED"],
            )
        return EvidenceLookupOutcome(result=EvidenceLookupResult.MATCH, record=record, reason_codes=[])

    def is_actionable(self, key: EvidenceKey, as_of: Optional[datetime] = None) -> bool:
        """True only for a fresh, exact-match APPROVED record. Every other outcome (missing,
        RESEARCH_ONLY, INSUFFICIENT, REJECTED, STALE) must block a trade proposal."""
        record = self.lookup(key, as_of)
        if record is None:
            return False
        return record.status in (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED)

    def all_records(self) -> List[EvidenceRecord]:
        return list(self._records.values())


evidence_store = EvidenceStore()
