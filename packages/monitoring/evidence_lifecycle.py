"""Phase 11: conservative, automatic evidence lifecycle actions driven by drift signals, plus
a manual-reset-only kill switch.

Every transition here moves toward MORE caution, never less: APPROVED -> DEGRADED -> STALE ->
DISABLED is the only direction this module can push a record. There is no function anywhere in
this file that can move a record back to an APPROVED status - re-promotion is Phase 12's
retraining workflow's job, and even that never auto-promotes (Section 17: a retrained model
always enters RESEARCH_ONLY). This module also never disables new proposals or trips the kill
switch silently - every automatic action is recorded to the evidence audit log with a reason.
"""

from typing import List, Optional

from packages.domain.entities import DriftAssessment
from packages.domain.enums import DriftSeverity
from packages.evidence.audit import EvidenceAuditLog, evidence_audit_log
from packages.evidence.models import EvidenceKey, EvidenceStatus
from packages.evidence.store import EvidenceStore

EVIDENCE_AUTO_DEGRADED = "evidence_auto_degraded"
EVIDENCE_AUTO_DISABLED = "evidence_auto_disabled"
KILL_SWITCH_TRIPPED = "kill_switch_tripped"
KILL_SWITCH_RESET = "kill_switch_reset"

# Only an already-APPROVED record can be automatically degraded; an already-DEGRADED record
# can be automatically disabled. Anything else (RESEARCH_ONLY, INSUFFICIENT, REJECTED, STALE,
# DISABLED) is left alone - there is nothing more conservative to move it to automatically, and
# a REJECTED/DISABLED record must never be silently "helped" back toward tradeable.
_DEGRADABLE_STATUSES = (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED)
_DISABLABLE_STATUSES = (EvidenceStatus.DEGRADED,)


def apply_drift_action(
    store: EvidenceStore, key: EvidenceKey, drift: DriftAssessment, audit_log: Optional[EvidenceAuditLog] = None,
) -> Optional[EvidenceStatus]:
    """Applies the conservative action implied by a drift assessment to the exact-match
    evidence record for `key`, if any action is warranted. Returns the new status, or None if
    no record exists for this exact key or no action was warranted (e.g. severity NONE/LOW, or
    the record is already at/past the target conservatism level)."""
    log = audit_log if audit_log is not None else evidence_audit_log
    record = store.lookup(key)
    if record is None:
        return None

    if drift.severity == DriftSeverity.SEVERE and record.status in (*_DEGRADABLE_STATUSES, *_DISABLABLE_STATUSES):
        new_status = EvidenceStatus.DISABLED
        event = EVIDENCE_AUTO_DISABLED
    elif drift.severity == DriftSeverity.MODERATE and record.status in _DEGRADABLE_STATUSES:
        new_status = EvidenceStatus.DEGRADED
        event = EVIDENCE_AUTO_DEGRADED
    else:
        return None

    updated = record.model_copy(update={"status": new_status})
    store.register(updated)
    log.record(event, f"{key.strategy_name}:{key.symbol}:{key.timeframe}", {
        "drift_metric": drift.metric_name, "severity": drift.severity.value, "new_status": new_status.value,
    })
    return new_status


class KillSwitch:
    """Automatic actions may only ever TRIP this switch, never reset it - resetting requires an
    explicit human actor, recorded by name (Section 4: no silent recovery from a safety-
    critical automatic action)."""

    def __init__(self) -> None:
        self._active = False
        self._reason_codes: List[str] = []

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def reason_codes(self) -> List[str]:
        return list(self._reason_codes)

    def trip(self, reason_code: str) -> None:
        self._active = True
        if reason_code not in self._reason_codes:
            self._reason_codes.append(reason_code)
        evidence_audit_log.record(KILL_SWITCH_TRIPPED, "system", {"reason_code": reason_code})

    def reset(self, actor: str) -> None:
        if not actor:
            raise ValueError("Kill switch reset requires a named human actor.")
        self._active = False
        self._reason_codes = []
        evidence_audit_log.record(KILL_SWITCH_RESET, "system", {"actor": actor})


def should_disable_new_proposals(kill_switch: KillSwitch) -> bool:
    return kill_switch.is_active
