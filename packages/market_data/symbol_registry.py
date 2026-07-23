from decimal import Decimal
from typing import Dict, List, Optional

from packages.market_data.models import SymbolInfo


class SymbolRegistry:
    """Central repository for canonical symbol normalization and exchange metadata."""

    def __init__(self):
        self._canonical_to_info: Dict[str, SymbolInfo] = {}
        self._exchange_to_canonical: Dict[str, str] = {}
        self._initialize_default_symbols()

    def _initialize_default_symbols(self):
        """Initializes default Spot MVP symbols for BTC/USDT and ETH/USDT."""
        btc_usdt = SymbolInfo(
            canonical_symbol="BTC/USDT",
            exchange_symbol="BTCUSDT",
            exchange="binance",
            base_asset="BTC",
            quote_asset="USDT",
            price_tick_size=Decimal("0.01"),
            quantity_step_size=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
            min_notional=Decimal("5.00"),
            status="TRADING",
            trading_permissions=["SPOT"]
        )

        eth_usdt = SymbolInfo(
            canonical_symbol="ETH/USDT",
            exchange_symbol="ETHUSDT",
            exchange="binance",
            base_asset="ETH",
            quote_asset="USDT",
            price_tick_size=Decimal("0.01"),
            quantity_step_size=Decimal("0.0001"),
            min_quantity=Decimal("0.0001"),
            min_notional=Decimal("5.00"),
            status="TRADING",
            trading_permissions=["SPOT"]
        )

        self.register_symbol(btc_usdt)
        self.register_symbol(eth_usdt)

    def register_symbol(self, info: SymbolInfo) -> None:
        """Registers a symbol info object into the registry."""
        self._canonical_to_info[info.canonical_symbol] = info
        self._exchange_to_canonical[info.exchange_symbol] = info.canonical_symbol

    def normalize(self, exchange_symbol: str) -> str:
        """Converts an exchange symbol (e.g. BTCUSDT) to canonical format (e.g. BTC/USDT)."""
        if exchange_symbol in self._exchange_to_canonical:
            return self._exchange_to_canonical[exchange_symbol]
        # Fallback heuristic for standard quote assets
        if exchange_symbol.endswith("USDT"):
            base = exchange_symbol[:-4]
            return f"{base}/USDT"
        return exchange_symbol

    def to_exchange_symbol(self, canonical_symbol: str) -> str:
        """Converts canonical symbol (e.g. BTC/USDT) to exchange format (e.g. BTCUSDT)."""
        if canonical_symbol in self._canonical_to_info:
            return self._canonical_to_info[canonical_symbol].exchange_symbol
        return canonical_symbol.replace("/", "")

    def get_symbol_info(self, canonical_symbol: str) -> Optional[SymbolInfo]:
        """Retrieves SymbolInfo for a given canonical symbol."""
        return self._canonical_to_info.get(canonical_symbol)

    def list_canonical_symbols(self) -> List[str]:
        """Lists all registered canonical symbols."""
        return list(self._canonical_to_info.keys())


# Singleton instance
symbol_registry = SymbolRegistry()
