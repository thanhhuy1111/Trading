from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.telemetry.models import PipelineLineageRecord


class PipelineLineageService:
    """Manages end-to-end pipeline lineage records for entity correlation and audit."""

    def __init__(self) -> None:
        self.records: List[PipelineLineageRecord] = []
        self.correlation_index: Dict[UUID, List[PipelineLineageRecord]] = {}

    def record_lineage(
        self,
        entity_type: str,
        entity_id: UUID,
        correlation_id: UUID,
        parent_entity_type: Optional[str] = None,
        parent_entity_id: Optional[UUID] = None,
        causation_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        symbol: Optional[str] = None,
        service: str = "trading_pipeline"
    ) -> PipelineLineageRecord:
        record = PipelineLineageRecord(
            lineage_id=uuid4(),
            entity_type=entity_type,
            entity_id=entity_id,
            parent_entity_type=parent_entity_type,
            parent_entity_id=parent_entity_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            session_id=session_id,
            symbol=symbol,
            service=service,
            created_at=datetime.now(timezone.utc)
        )

        self.records.append(record)
        if correlation_id not in self.correlation_index:
            self.correlation_index[correlation_id] = []
        self.correlation_index[correlation_id].append(record)

        logger.debug(
            "Pipeline lineage recorded",
            extra={
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "correlation_id": str(correlation_id)
            }
        )
        return record

    def get_lineage_by_correlation(self, correlation_id: UUID) -> List[PipelineLineageRecord]:
        return self.correlation_index.get(correlation_id, [])

    def get_all_lineage(self, limit: int = 100) -> List[PipelineLineageRecord]:
        return self.records[-limit:]


lineage_service = PipelineLineageService()
