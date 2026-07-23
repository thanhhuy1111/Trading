import hashlib

from packages.backtest.models import BacktestConfig


class ReproducibilityVerifier:
    """Generates SHA256 reproducibility fingerprints and verifies execution identity."""

    def compute_fingerprint(
        self,
        dataset_checksum: str,
        config: BacktestConfig,
        code_version: str = "1.0.0"
    ) -> str:
        """Compute SHA256 reproducibility fingerprint."""
        hasher = hashlib.sha256()

        raw_str = (
            f"DATASET:{dataset_checksum}|"
            f"MODE:{config.mode.value}|"
            f"SEED:{config.random_seed}|"
            f"CASH:{config.initial_cash}|"
            f"SAME_BAR:{config.liquidity_config.same_bar_fill_allowed}|"
            f"CODE:{code_version}|"
            f"FEATURE_VER:{config.feature_set_version}|"
            f"RISK_VER:{config.risk_policy_version}|"
            f"STRATEGY_CONFIG:{config.strategy_config.config_hash}"
        )
        hasher.update(raw_str.encode("utf-8"))
        return hasher.hexdigest()

    def verify_reproducibility(
        self,
        fingerprint1: str,
        fingerprint2: str
    ) -> bool:
        """Verify fingerprint matching."""
        return fingerprint1 == fingerprint2


reproducibility_verifier = ReproducibilityVerifier()
