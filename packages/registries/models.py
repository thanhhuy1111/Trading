"""Phase 3: registry entry model shared by all seven artifact registries."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from packages.domain.enums import RegistryEntryStatus


class RegistryEntry(BaseModel):
    entry_id: UUID = Field(default_factory=uuid4)
    name: str
    version: str
    status: RegistryEntryStatus = RegistryEntryStatus.DRAFT
    artifact_location: Optional[str] = None
    artifact_checksum: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    code_commit: Optional[str] = None
    configuration_hash: Optional[str] = None
    dependencies: Dict[str, str] = Field(default_factory=dict)
    compatible_symbols: List[str] = Field(default_factory=list)   # empty == universal
    compatible_timeframes: List[str] = Field(default_factory=list)  # empty == universal
    reason_codes: List[str] = Field(default_factory=list)

    def key(self) -> tuple:
        return (self.name, self.version)

    def is_compatible(self, symbol: Optional[str], timeframe: Optional[str]) -> bool:
        """Exact-match compatibility: an entry scoped to specific symbols/timeframes must
        exact-match the request; an entry with an EMPTY compatibility list is explicitly
        universal (declared, not implied) — never a partial/fuzzy match either way."""
        if self.compatible_symbols and symbol not in self.compatible_symbols:
            return False
        if self.compatible_timeframes and timeframe not in self.compatible_timeframes:
            return False
        return True
