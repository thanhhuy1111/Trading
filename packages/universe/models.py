"""Dynamic Trading Universe: eligibility model and deterministic snapshot.

Selection logic (selector.py) is a pure function over already-fetched `SymbolMetadata` — it
never calls the network itself, so it can be unit-tested offline with fixtures. Only
`live_source.py` touches the network, and only when explicitly invoked (opt-in refresh).
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

UNIVERSE_VERSION = "universe_v1"

# Known stablecoin base assets to exclude even if quoted in USDT (a stablecoin/USDT pair is not
# a directional trading opportunity). Reviewed manually, not derived from an API flag — Binance
# does not expose a "is_stablecoin" field.
KNOWN_STABLECOIN_BASE_ASSETS = {
    "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "USTC", "GUSD", "EURT", "PYUSD",
}

# Binance leveraged-token naming convention: <ASSET><3-5x><UP|DOWN|BULL|BEAR>. Checked via
# suffix on the base asset.
LEVERAGED_TOKEN_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


class ExclusionReason(str, Enum):
    NOT_SPOT_TRADING_ENABLED = "NOT_SPOT_TRADING_ENABLED"
    NOT_USDT_QUOTED = "NOT_USDT_QUOTED"
    IS_STABLECOIN = "IS_STABLECOIN"
    IS_LEVERAGED_TOKEN = "IS_LEVERAGED_TOKEN"
    DELISTED_OR_HALTED = "DELISTED_OR_HALTED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_QUOTE_VOLUME = "INSUFFICIENT_QUOTE_VOLUME"
    INSUFFICIENT_DATA_COMPLETENESS = "INSUFFICIENT_DATA_COMPLETENESS"
    EXCESSIVE_SPREAD = "EXCESSIVE_SPREAD"
    METADATA_UNAVAILABLE = "METADATA_UNAVAILABLE"


class UniverseSelectionRules(BaseModel):
    """All thresholds in one place, versioned via UNIVERSE_VERSION. Change a value here only
    by bumping the version — old snapshots keep the rules that actually produced them."""

    min_history_days: int = 730           # >= 2 years of daily history
    min_quote_volume_24h_usdt: Decimal = Decimal("10000000")   # $10M/day
    min_recent_candle_completeness_pct: Decimal = Decimal("95.0")  # over the trailing window checked
    recent_completeness_window_days: int = 30
    max_spread_bps: Decimal = Decimal("15.0")  # (ask-bid)/mid, in basis points


class SymbolMetadata(BaseModel):
    """Raw, already-fetched inputs the selector needs. Constructing one of these from real
    data is live_source.py's job; the selector only ever consumes this shape."""

    symbol: str  # canonical, e.g. "BTC/USDT"
    exchange_symbol: str  # e.g. "BTCUSDT"
    base_asset: str
    quote_asset: str
    status: str  # Binance symbol status, e.g. "TRADING", "BREAK", "HALT"
    is_spot_trading_allowed: bool
    history_days_available: Optional[int] = None
    quote_volume_24h_usdt: Optional[Decimal] = None
    recent_candle_completeness_pct: Optional[Decimal] = None
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    metadata_available: bool = True


class SymbolEvaluation(BaseModel):
    symbol: str
    eligible: bool
    exclusion_reasons: List[ExclusionReason] = Field(default_factory=list)
    metadata: SymbolMetadata


class UniverseSnapshot(BaseModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    universe_version: str = UNIVERSE_VERSION
    generated_at: datetime
    selection_rules: UniverseSelectionRules
    eligible_symbols: List[str]
    excluded_symbols: List[str]
    exclusion_reasons: dict  # symbol -> list[ExclusionReason.value]
    metadata_checksum: str = ""

    def compute_checksum(self) -> str:
        payload = json.dumps(
            {
                "universe_version": self.universe_version,
                "selection_rules": json.loads(self.selection_rules.model_dump_json()),
                "eligible_symbols": sorted(self.eligible_symbols),
                "excluded_symbols": sorted(self.excluded_symbols),
                "exclusion_reasons": {k: sorted(v) for k, v in self.exclusion_reasons.items()},
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
