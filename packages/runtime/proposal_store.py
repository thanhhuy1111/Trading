"""Shared, process-global, bounded in-memory `TradeProposal` cache.

Ephemeral, not persisted across restarts (Phase 10's shadow storage is the durable record) --
this exists purely so a caller can re-fetch what `/recommendations/analyze`, `/scan`, or the
chat advisor's `scan_trade_opportunities` tool just handed back, without re-running the whole
pipeline. Bounded so a long-running process can't leak memory from repeated calls.

Both `apps/api/routers/recommendations.py` and `packages/chat_agent/tool_registry.py` read
and write through this single store, so a proposal created via one surface is fetchable from
the other.
"""

from typing import Dict, List, Optional
from uuid import UUID

from packages.domain.entities import TradeProposal

_MAX_STORED_PROPOSALS = 2000


class ProposalStore:
    def __init__(self, max_size: int = _MAX_STORED_PROPOSALS) -> None:
        self._max_size = max_size
        self._proposals: Dict[UUID, TradeProposal] = {}

    def remember(self, proposals: List[TradeProposal]) -> None:
        for p in proposals:
            self._proposals[p.proposal_id] = p
        if len(self._proposals) > self._max_size:
            for old_id in list(self._proposals)[: len(self._proposals) - self._max_size]:
                del self._proposals[old_id]

    def get(self, proposal_id: UUID) -> Optional[TradeProposal]:
        return self._proposals.get(proposal_id)

    def get_by_str(self, proposal_id: str) -> Optional[TradeProposal]:
        try:
            return self.get(UUID(proposal_id))
        except ValueError:
            return None


proposal_store = ProposalStore()
