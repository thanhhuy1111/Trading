"""In-memory model registry.

Deliberately ships EMPTY: no trained artifact is registered anywhere in this repository.
`PredictionService.predict()` falls back to `calibration_status=UNAVAILABLE` for every
symbol/timeframe/horizon until an offline training pipeline calls `model_registry.register()`
(e.g. from a startup hook backed by a persisted artifact store, once one exists). This is a
deliberate scope boundary, not an oversight -- see docs/AI_TRADING_ADVISOR_ARCHITECTURE.md.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple

from packages.prediction.direction_model import DirectionModel
from packages.prediction.meta_label_model import MetaLabelModel
from packages.prediction.return_model import ReturnModel
from packages.prediction.volatility_model import VolatilityModel


@dataclass(frozen=True)
class ModelArtifact:
    symbol: str
    timeframe: str
    horizon_minutes: int
    model_version: str
    feature_version: str
    direction_model: DirectionModel
    return_model: ReturnModel
    volatility_model: VolatilityModel
    meta_label_model: MetaLabelModel
    calibration_score: Optional[Decimal] = None
    dataset_checksum: Optional[str] = None
    trained_at: Optional[datetime] = None


class ModelRegistry:
    def __init__(self) -> None:
        self._artifacts: Dict[Tuple[str, str, int], ModelArtifact] = {}

    def register(self, artifact: ModelArtifact) -> None:
        key = (artifact.symbol, artifact.timeframe, artifact.horizon_minutes)
        self._artifacts[key] = artifact

    def lookup(self, symbol: str, timeframe: str, horizon_minutes: int) -> Optional[ModelArtifact]:
        return self._artifacts.get((symbol, timeframe, horizon_minutes))

    def unregister(self, symbol: str, timeframe: str, horizon_minutes: int) -> None:
        self._artifacts.pop((symbol, timeframe, horizon_minutes), None)

    def clear(self) -> None:
        self._artifacts.clear()

    def __len__(self) -> int:
        return len(self._artifacts)


model_registry = ModelRegistry()
