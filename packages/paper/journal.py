import hashlib
from datetime import datetime, timezone
from typing import Dict, List
from uuid import UUID, uuid4

from packages.paper.models import PaperEventJournalEntry


class PaperEventJournal:
    """Append-only durable event journal for paper trading audit and replay."""

    def __init__(self) -> None:
        self.entries: List[PaperEventJournalEntry] = []
        self.session_sequence: Dict[UUID, int] = {}

    def append_event(
        self,
        session_id: UUID,
        event_type: str,
        event_id: UUID,
        source: str,
        exchange_event_time: datetime,
        payload_str: str
    ) -> PaperEventJournalEntry:
        seq = self.session_sequence.get(session_id, 0) + 1
        self.session_sequence[session_id] = seq

        hasher = hashlib.sha256()
        hasher.update(f"{session_id}:{seq}:{event_type}:{payload_str}".encode("utf-8"))
        checksum = hasher.hexdigest()

        now = datetime.now(timezone.utc)

        entry = PaperEventJournalEntry(
            journal_id=uuid4(),
            session_id=session_id,
            event_type=event_type,
            event_id=event_id,
            source=source,
            exchange_event_time=exchange_event_time,
            received_at=now,
            processed_at=now,
            sequence_number=seq,
            payload_checksum=checksum,
            schema_version=1
        )

        self.entries.append(entry)
        return entry

    def get_session_entries(self, session_id: UUID) -> List[PaperEventJournalEntry]:
        return [e for e in self.entries if e.session_id == session_id]


paper_event_journal = PaperEventJournal()
