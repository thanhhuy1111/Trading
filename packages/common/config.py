from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global system configuration backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # App & Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SYSTEM_MODE: str = "PAPER_TRADING"  # BACKTEST, PAPER_TRADING, LIVE_TRADING
    LIVE_TRADING_ENABLED: bool = False
    PRIVATE_EXCHANGE_API_ENABLED: bool = False
    FEATURE_FLAGS_LIVE_TRADING: bool = False
    FEATURE_ADVANCED_NEWS: bool = False
    FEATURE_ADVANCED_ONCHAIN: bool = False
    FEATURE_ADVANCED_MACRO: bool = False
    FEATURE_ADVANCED_SENTIMENT: bool = False
    FEATURE_ADVANCED_REGIME: bool = False
    FEATURE_ADVANCED_ETH: bool = False
    FEATURE_ADVANCED_REFLECTION: bool = False
    FEATURE_ADVANCED_DYNAMIC_WEIGHTS: bool = False

    # Server API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Databases & Services
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "trading_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/trading_db"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_DB: str = "trading_analytics"

    REDPANDA_BROKERS: str = "localhost:9092"

    # Exchange Configuration
    BINANCE_API_KEY: str = ""
    BINANCE_SECRET_KEY: str = ""
    BINANCE_TESTNET: bool = True
    EXCHANGE_NAME: str = "binance_spot"
    FUTURES_EXCHANGE_NAME: str = "binance_usdm_futures"
    DERIVATIVES_CACHE_TTL_SECONDS: int = 30

    # Trading Risk Parameters
    DEFAULT_SYMBOLS: str = "BTCUSDT,ETHUSDT"
    TIMEFRAMES: str = "15m,1h,4h"
    MAX_RISK_PER_TRADE_PCT: float = 0.0025    # 0.25% NAV
    MAX_OPEN_RISK_PCT: float = 0.015         # 1.5% NAV
    MAX_DAILY_LOSS_PCT: float = 0.015        # 1.5% NAV
    HARD_STOP_DRAWDOWN_PCT: float = 0.08      # 8.0% NAV

    @property
    def symbols_list(self) -> List[str]:
        return [s.strip() for s in self.DEFAULT_SYMBOLS.split(",") if s.strip()]

    @property
    def timeframes_list(self) -> List[str]:
        return [t.strip() for t in self.TIMEFRAMES.split(",") if t.strip()]


settings = Settings()
