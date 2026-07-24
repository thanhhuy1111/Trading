"""Generic artifact registry: exact-match lookup by (name, version), with status transitions
and compatibility-scoped queries. Shared implementation behind all seven Phase 3 registries so
their exact-match/no-fallback behavior can't drift between instances."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from packages.domain.enums import RegistryEntryStatus
from packages.registries.models import RegistryEntry

# Allowed status transitions — anything not listed here is rejected, so a caller can't, say,
# jump straight from DRAFT to APPROVED without going through VALIDATED, or resurrect a
# REJECTED entry silently.
_S = RegistryEntryStatus
_ALLOWED_TRANSITIONS: Dict[RegistryEntryStatus, List[RegistryEntryStatus]] = {
    _S.DRAFT: [_S.RESEARCH_ONLY, _S.REJECTED],
    _S.RESEARCH_ONLY: [_S.VALIDATED, _S.REJECTED, _S.DISABLED],
    _S.VALIDATED: [_S.APPROVED, _S.REJECTED, _S.DISABLED],
    _S.APPROVED: [_S.DEGRADED, _S.STALE, _S.DISABLED],
    _S.DEGRADED: [_S.APPROVED, _S.STALE, _S.DISABLED],
    _S.STALE: [_S.APPROVED, _S.DISABLED],
    _S.DISABLED: [],
    _S.REJECTED: [],
}


class InvalidStatusTransitionError(Exception):
    pass


class DuplicateRegistryEntryError(Exception):
    pass


class ArtifactRegistry:
    def __init__(self, registry_name: str) -> None:
        self.registry_name = registry_name
        self._entries: Dict[Tuple[str, str], RegistryEntry] = {}

    def register(self, entry: RegistryEntry) -> RegistryEntry:
        if entry.key() in self._entries:
            raise DuplicateRegistryEntryError(
                f"REGISTRY_ENTRY_EXISTS: {self.registry_name}:{entry.name}:{entry.version}"
            )
        self._entries[entry.key()] = entry
        return entry

    def get(self, name: str, version: str) -> Optional[RegistryEntry]:
        """Exact (name, version) match only — no "latest" fallback, no nearest-version match."""
        return self._entries.get((name, version))

    def transition_status(
        self, name: str, version: str, new_status: RegistryEntryStatus,
        reason_codes: Optional[List[str]] = None,
    ) -> RegistryEntry:
        entry = self.get(name, version)
        if entry is None:
            raise KeyError(f"REGISTRY_ENTRY_NOT_FOUND: {self.registry_name}:{name}:{version}")
        allowed = _ALLOWED_TRANSITIONS.get(entry.status, [])
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"{self.registry_name}:{name}:{version} cannot transition {entry.status.value} -> {new_status.value}"
            )
        updated = entry.model_copy(update={
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
            "reason_codes": tuple(reason_codes or []),
        })
        self._entries[entry.key()] = updated
        return updated

    def find_compatible(
        self, symbol: Optional[str] = None, timeframe: Optional[str] = None,
        status: Optional[RegistryEntryStatus] = None,
    ) -> List[RegistryEntry]:
        results = [e for e in self._entries.values() if e.is_compatible(symbol, timeframe)]
        if status is not None:
            results = [e for e in results if e.status == status]
        return results

    def all_entries(self) -> List[RegistryEntry]:
        return list(self._entries.values())
