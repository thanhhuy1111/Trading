"""Expected volatility over the prediction horizon.

Unlike direction/return, this does not require a trained artifact: realized 20-period
volatility straight from the feature engine is itself a legitimate, real, non-fabricated
quantitative fact (a measurement, not a forecast). It is deliberately always "available"
so a candidate is never blocked purely for lack of a volatility model; PredictionService
still requires the direction model to be calibrated before any probability is emitted.
"""

from decimal import Decimal
from typing import Optional, Protocol

from packages.features.models import FeatureSnapshot
from packages.prediction.feature_adapter import realized_volatility_bps


class VolatilityModel(Protocol):
    model_version: str

    def predict_expected_volatility_bps(self, snapshot: FeatureSnapshot) -> Optional[Decimal]: ...


class RealizedVolatilityModel:
    """Uses trailing realized volatility as a same-order-of-magnitude proxy for the
    expected volatility over the (short) prediction horizon. Documented as a proxy, not a
    calibrated volatility forecast (e.g. GARCH), in every ModelPrediction it feeds.
    """

    model_version = "realized_vol_v1"

    def predict_expected_volatility_bps(self, snapshot: FeatureSnapshot) -> Optional[Decimal]:
        return realized_volatility_bps(snapshot)


realized_volatility_model = RealizedVolatilityModel()
