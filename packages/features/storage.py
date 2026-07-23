import json
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.features.models import (
    FeatureSnapshot,
)
from packages.market_data.models import Timeframe


class FeatureStoreRepository:
    """PostgreSQL Feature Store Repository for feature definitions, feature sets, and snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_snapshot(self, snapshot: FeatureSnapshot) -> None:
        query = text("""
            INSERT INTO feature_snapshots (
                snapshot_id, exchange, symbol, timeframe, feature_set, feature_set_version,
                event_time, as_of_time, computed_at, lookback_start, lookback_end,
                values, quality_status, quality_issues, source_data_version, lineage, schema_version, created_at
            ) VALUES (
                :snapshot_id, :exchange, :symbol, :timeframe, :feature_set, :feature_set_version,
                :event_time, :as_of_time, :computed_at, :lookback_start, :lookback_end,
                :values, :quality_status, :quality_issues, :source_data_version, :lineage, :schema_version, NOW()
            )
            ON CONFLICT (exchange, symbol, timeframe, feature_set, feature_set_version, as_of_time)
            DO NOTHING
        """)

        # Serialize values dictionary (converting Decimals to strings for JSON)
        serialized_values = {
            k: str(v) if v is not None else None for k, v in snapshot.values.items()
        }

        params = {
            "snapshot_id": str(snapshot.snapshot_id),
            "exchange": snapshot.exchange,
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe.value,
            "feature_set": snapshot.feature_set,
            "feature_set_version": snapshot.feature_set_version,
            "event_time": snapshot.event_time,
            "as_of_time": snapshot.as_of_time,
            "computed_at": snapshot.computed_at,
            "lookback_start": snapshot.lookback_start,
            "lookback_end": snapshot.lookback_end,
            "values": json.dumps(serialized_values),
            "quality_status": snapshot.quality_status.value,
            "quality_issues": json.dumps([i.model_dump(mode="json") for i in snapshot.quality_issues]),
            "source_data_version": snapshot.source_data_version,
            "lineage": json.dumps(snapshot.lineage.model_dump(mode="json")),
            "schema_version": snapshot.schema_version,
        }

        await self.session.execute(query, params)

    async def get_latest_snapshot(
        self, exchange: str, symbol: str, timeframe: Timeframe, feature_set: str
    ) -> Optional[Dict[str, Any]]:
        query = text("""
            SELECT snapshot_id, exchange, symbol, timeframe, feature_set, feature_set_version,
                   event_time, as_of_time, computed_at, values, quality_status
            FROM feature_snapshots
            WHERE exchange = :exchange AND symbol = :symbol AND timeframe = :timeframe AND feature_set = :feature_set
            ORDER BY as_of_time DESC
            LIMIT 1
        """)
        result = await self.session.execute(query, {
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe.value,
            "feature_set": feature_set,
        })
        row = result.fetchone()
        if not row:
            return None
        return dict(row._mapping)
