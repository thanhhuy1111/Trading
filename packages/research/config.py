"""Versioned research configuration.

Every sub-config here contributes to `ResearchConfig.config_hash` (same pattern as
`packages.agents.strategy_config.StrategyConfig.config_hash`), so a dataset/model/
evaluation/evidence artifact's recorded `config_hash` uniquely identifies every threshold
that produced it. Research thresholds live here, never hardcoded in pipeline code.

Configs are loaded from YAML files (see `configs/research/*.yaml`, `configs/models/*.yaml`),
not environment variables -- these are per-experiment research parameters, not deployment
settings.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, ConfigDict, Field

from packages.prediction.feature_adapter import FEATURE_NAMES

SUPPORTED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
SUPPORTED_TIMEFRAMES = ["15m", "1h", "4h"]
SUPPORTED_HORIZONS_MINUTES = [60, 240, 720]


class DatasetConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "1.0.0"
    symbols: List[str] = Field(default_factory=lambda: list(SUPPORTED_SYMBOLS))
    timeframes: List[str] = Field(default_factory=lambda: list(SUPPORTED_TIMEFRAMES))
    start_time: datetime
    end_time: datetime
    source: str = "binance_public"
    source_version: str = "1.0.0"
    warmup_periods: int = 60


class FeatureConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "standard_v1"
    feature_names: List[str] = Field(default_factory=lambda: list(FEATURE_NAMES))
    missing_value_policy: str = "ZERO_FILL_NO_FORWARD_FILL"


class LabelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "triple_barrier_v1"
    horizons_minutes: List[int] = Field(default_factory=lambda: list(SUPPORTED_HORIZONS_MINUTES))
    upper_barrier_pct: Decimal = Decimal("0.02")
    lower_barrier_pct: Decimal = Decimal("0.02")
    use_cost_estimator: bool = True


class SplitConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str = "walk_forward"
    train_fraction: Decimal = Decimal("0.6")
    validation_fraction: Decimal = Decimal("0.2")
    test_fraction: Decimal = Decimal("0.2")
    num_folds: int = 3
    purge_hours: int = 24
    embargo_hours: int = 24


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_type: str = "logistic_regression"
    model_version: str = "logreg_v1"
    hyperparameters: Dict[str, Any] = Field(default_factory=lambda: {"C": 1.0, "max_iter": 1000})
    random_seed: int = 42


class CalibrationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str = "platt"  # "platt" | "isotonic"
    n_bins: int = 10


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    probability_buckets: int = 10
    annualization_note: str = (
        "Sharpe/Sortino/Calmar are computed per-trade (not annualized) because trade "
        "events are irregularly spaced; see docs/ALPHA_WALK_FORWARD_VALIDATION.md."
    )


class ApprovalGateConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_oos_expectancy_bps: Decimal = Decimal("0.0")
    min_profit_factor: Decimal = Decimal("1.20")
    min_sharpe: Decimal = Decimal("1.00")
    max_drawdown_pct: Decimal = Decimal("20.0")
    min_oos_trades: int = 100
    min_walk_forward_windows: int = 3
    max_single_window_profit_share: Decimal = Decimal("0.60")
    min_calibration_score: Decimal = Decimal("0.50")


class ResearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    dataset: DatasetConfig
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    labels: LabelConfig = Field(default_factory=LabelConfig)
    splits: SplitConfig = Field(default_factory=SplitConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    approval: ApprovalGateConfig = Field(default_factory=ApprovalGateConfig)

    @property
    def config_hash(self) -> str:
        payload = json.dumps(_json_safe(self.model_dump()), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (Decimal, datetime)):
        return str(obj)
    return obj


def load_research_config(path: str) -> ResearchConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ResearchConfig(**raw)


def load_model_config(path: str) -> ModelConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ModelConfig(**raw)
