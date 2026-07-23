"""Exact asset/timeframe/model evidence binding.

An EvidenceRecord is a claim of the form "this exact strategy+model+feature+label
combination, on this exact symbol and timeframe, using this exact dataset and gate version,
produced this result." Every one of those fields must match exactly for a lookup to return a
record — there is deliberately no similarity/fallback matching (see store.py), because a
result on BTC/USDT 1D says nothing evidentiary about ETH/USDT 1D or BTC/USDT 4h, and a result
under gate_v1 says nothing about whether the same run would clear a tightened gate_v2.
"""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import List, NamedTuple, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    # Cleared the promotion gate independently on every symbol the campaign tested it against.
    UNIVERSAL_APPROVED = "UNIVERSAL_APPROVED"
    # Cleared the promotion gate on this exact symbol/timeframe, but not (or not yet tested)
    # on every symbol in scope.
    ASSET_SPECIFIC_APPROVED = "ASSET_SPECIFIC_APPROVED"
    # Some out-of-sample signal (e.g. gross-profitable, or fails only on a soft criterion) but
    # does not clear the full promotion gate. Never usable as trading evidence.
    RESEARCH_ONLY = "RESEARCH_ONLY"
    # Not enough out-of-sample trades/folds to judge either way.
    INSUFFICIENT = "INSUFFICIENT"
    # Clearly failed the gate (negative expectancy/Sharpe, etc.).
    REJECTED = "REJECTED"
    # Was previously APPROVED but has aged past the freshness window or been superseded by a
    # newer dataset/gate/code version for the same key.
    STALE = "STALE"


class EvidenceKey(NamedTuple):
    """The exact-match binding tuple. Every field participates in equality — this is a
    NamedTuple specifically so lookups are plain tuple equality with no normalization,
    fuzzy matching, or partial-key fallback possible."""
    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    model_type: str
    model_version: str
    feature_version: str
    label_version: str
    dataset_checksum: str
    gate_version: str
    config_hash: str
    code_commit: str


class EvidenceRecord(BaseModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    key: EvidenceKey
    status: EvidenceStatus
    generated_at: datetime
    # Compact, human-checkable justification — the real numbers behind the status, not a
    # restatement of it.
    total_oos_trades: int
    mean_oos_sharpe: Optional[str] = None
    worst_fold_drawdown_pct: Optional[str] = None
    aggregate_net_profit: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None

    def is_stale(self, as_of: Optional[datetime] = None) -> bool:
        as_of = as_of or datetime.now(timezone.utc)
        return self.expires_at is not None and as_of > self.expires_at


def compute_evidence_dataset_checksum(fold_dataset_checksums: List[str]) -> str:
    """Walk-forward evidence spans multiple per-fold datasets (each fold is backtested on its
    own sliced dataset — see packages/research/campaign.py), so there is no single contiguous
    dataset checksum to bind to. This combines the sorted per-fold checksums deterministically
    so the same set of folds always produces the same combined checksum, and any change to any
    fold's data changes it."""
    hasher = hashlib.sha256()
    for cs in sorted(fold_dataset_checksums):
        hasher.update(cs.encode("utf-8"))
    return hasher.hexdigest()
