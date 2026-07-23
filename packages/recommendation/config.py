from decimal import Decimal
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class RecommendationConfig(BaseSettings):
    """Config-driven thresholds for the recommendation domain.

    Every numeric gate the plan calls out as "must be configuration-driven, not an
    arbitrary constant embedded in strategy or API code" lives here. Values are the
    conservative v1 defaults; override via environment variables (prefix
    RECOMMENDATION_) or a .env file, never by editing code.
    """

    model_config = SettingsConfigDict(
        env_prefix="RECOMMENDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Universe (v1 scope, per implementation plan section 3.1) ---
    supported_symbols: str = "BTCUSDT,ETHUSDT"
    supported_timeframes: str = "15m,1h,4h"
    supported_side: str = "LONG_ONLY"

    # --- Opportunity gates (section 11 / 9 of the two plans) ---
    min_probability_profit: Decimal = Decimal("0.58")
    min_risk_reward_ratio: Decimal = Decimal("1.5")
    min_expected_net_return_bps: Decimal = Decimal("0.0")
    min_calibration_score: Decimal = Decimal("0.50")
    max_market_data_staleness_seconds: int = 90
    max_spread_bps: Decimal = Decimal("15.0")
    min_liquidity_score: Decimal = Decimal("0.40")

    # --- Proposal shape ---
    max_proposals: int = 3
    default_proposal_ttl_minutes: int = 60
    entry_chase_bps: Decimal = Decimal("15.0")  # max distance above reference the entry zone may chase

    # --- Ranker weights (all components normalized to [0,1] before combining) ---
    ranker_probability_weight: Decimal = Decimal("1.0")
    ranker_return_weight: Decimal = Decimal("1.0")
    ranker_regime_weight: Decimal = Decimal("1.0")
    ranker_liquidity_weight: Decimal = Decimal("1.0")
    ranker_evidence_weight: Decimal = Decimal("1.0")
    ranker_return_normalization_bps: Decimal = Decimal("200.0")
    ranker_downside_floor: Decimal = Decimal("0.05")

    # --- Development-only fixture mode (section 15 / 4) ---
    # Never enable in a deployment that serves real users; fixture proposals are always
    # tagged TEST_DATA / SIMULATED / NOT_A_REAL_RECOMMENDATION and gated separately.
    recommendation_dev_fixture_mode: bool = False

    @property
    def symbols_list(self) -> List[str]:
        return [s.strip().upper() for s in self.supported_symbols.split(",") if s.strip()]

    @property
    def timeframes_list(self) -> List[str]:
        return [t.strip() for t in self.supported_timeframes.split(",") if t.strip()]


recommendation_config = RecommendationConfig()
