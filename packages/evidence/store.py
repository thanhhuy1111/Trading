"""In-memory exact-match evidence registry.

`lookup` performs plain dict equality on the full EvidenceKey tuple — nothing here does
prefix matching, "closest" matching, or falls back across symbol/timeframe/model_version. If a
key isn't registered exactly as asked, the answer is "no evidence", never "here's the nearest
thing we have."
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus


class EvidenceStore:
    def __init__(self) -> None:
        self._records: Dict[EvidenceKey, EvidenceRecord] = {}

    def register(self, record: EvidenceRecord) -> None:
        self._records[record.key] = record

    def lookup(self, key: EvidenceKey, as_of: Optional[datetime] = None) -> Optional[EvidenceRecord]:
        """Exact match only. Returns None if this exact (strategy_name, strategy_version,
        symbol, timeframe, model_type, model_version, feature_version, label_version,
        dataset_checksum, gate_version, config_hash, code_commit) tuple was never registered —
        callers must treat that identically to REJECTED for trading-decision purposes (i.e.
        "no usable evidence"), never substitute a different key's record."""
        record = self._records.get(key)
        if record is None:
            return None
        if record.status in (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED) and record.is_stale(as_of):
            # Return a STALE view rather than the stored APPROVED status — staleness is a
            # function of "now", not a stored field that needs a separate write path.
            return record.model_copy(update={"status": EvidenceStatus.STALE})
        return record

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
