"""In-memory store of proposals produced by the most recent scan(s).

Backs `analyze_trade_proposal` (retrieve by ID, no recomputation) and
`validate_trade_proposal` (retrieve by ID, then re-run `proposal_validator.validate_proposal`
against current time). A proposal that has fallen out of the store (process restart, or
older than the store's retention) simply cannot be found -- callers must treat that as
"unknown proposal", never re-synthesize one.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from packages.recommendation.models import TradeProposal


class ProposalStore:
    def __init__(self, max_size: int = 2000) -> None:
        self._by_id: Dict[str, TradeProposal] = {}
        self._max_size = max_size

    def put(self, proposal: TradeProposal) -> None:
        self._by_id[proposal.proposal_id] = proposal
        if len(self._by_id) > self._max_size:
            oldest_id = min(self._by_id, key=lambda pid: self._by_id[pid].generated_at)
            del self._by_id[oldest_id]

    def put_many(self, proposals: List[TradeProposal]) -> None:
        for p in proposals:
            self.put(p)

    def get(self, proposal_id: str) -> Optional[TradeProposal]:
        return self._by_id.get(proposal_id)

    def purge_expired(self, now: Optional[datetime] = None) -> int:
        eval_time = now or datetime.now(timezone.utc)
        expired_ids = [pid for pid, p in self._by_id.items() if p.expires_at <= eval_time]
        for pid in expired_ids:
            del self._by_id[pid]
        return len(expired_ids)

    def __len__(self) -> int:
        return len(self._by_id)


proposal_store = ProposalStore()
