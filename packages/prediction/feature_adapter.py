"""Adapts a real FeaturePipeline FeatureSnapshot into a plain float feature vector.

Pure, deterministic, no I/O. Missing/invalid feature values become 0.0 rather than being
silently dropped, so the vector shape is always stable for a fixed FEATURE_NAMES list.
"""

from decimal import Decimal
from typing import Dict

from packages.features.models import FeatureSnapshot

FEATURE_NAMES = [
    "return_1p",
    "return_3p",
    "return_5p",
    "high_low_range",
    "ema_20_slope",
    "adx_14",
    "rsi_14",
    "atr_14",
    "volatility_20",
    "relative_volume_20",
    "zscore_20",
    "bollinger_pos_20",
    "donchian_breakout_20",
]


def to_feature_vector(snapshot: FeatureSnapshot) -> Dict[str, float]:
    vector: Dict[str, float] = {}
    for name in FEATURE_NAMES:
        raw = snapshot.values.get(name)
        if raw is None:
            vector[name] = 0.0
        elif isinstance(raw, bool):
            vector[name] = 1.0 if raw else 0.0
        elif isinstance(raw, Decimal):
            vector[name] = float(raw)
        else:
            vector[name] = float(raw)
    return vector


def realized_volatility_bps(snapshot: FeatureSnapshot) -> "Decimal | None":
    """The only "prediction" that needs no trained model: realized 20-period volatility,
    directly from the feature engine, expressed in bps. This is a real measurement, not a
    forecast, and is always available whenever the volatility_20 feature is available.
    """
    raw = snapshot.values.get("volatility_20")
    if raw is None:
        return None
    return Decimal(str(raw)) * Decimal("10000")
