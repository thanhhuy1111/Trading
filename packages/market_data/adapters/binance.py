import asyncio
import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator, Dict, List, Sequence

from packages.common.logger import logger
from packages.market_data.models import (
    Candle,
    CandleUpdate,
    DataQualityStatus,
    ExchangeInfo,
    MarketTrade,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
    SymbolInfo,
    Timeframe,
)
from packages.market_data.symbol_registry import symbol_registry


def _get_ssl_context() -> ssl.SSLContext:
    """Return a certificate-verifying TLS context for public market-data requests."""
    return ssl.create_default_context()


class BinancePublicMarketDataProvider:
    """Read-Only Public Binance Market Data Provider.
    
    CRITICAL SAFETY RULES:
    1. Uses PUBLIC API endpoints ONLY (api.binance.com / testnet.binance.vision).
    2. NO trading API keys or private user streams.
    3. NO order placement methods exist on this class.
    """

    REST_BASE_URL = "https://api.binance.com"
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"

    TIMEFRAME_MAP = {
        Timeframe.M1: "1m",
        Timeframe.M5: "5m",
        Timeframe.M15: "15m",
        Timeframe.H1: "1h",
        Timeframe.H4: "4h",
        Timeframe.D1: "1d",
    }

    def __init__(self, exchange_id: str = "binance"):
        self.exchange_id = exchange_id

    async def get_exchange_info(self) -> ExchangeInfo:
        """Fetches public exchange info."""
        return ExchangeInfo(
            exchange_id=self.exchange_id,
            name="Binance Public Spot Exchange",
            is_active=True
        )

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = symbol_registry.get_symbol_info(symbol)
        if not info:
            raise ValueError(f"Symbol '{symbol}' not found in registry")
        return info

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int = 500,
    ) -> Sequence[Candle]:
        """Fetches historical public klines/candles from Binance public REST API."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        tf_str = self.TIMEFRAME_MAP.get(timeframe, "1m")
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        url = (
            f"{self.REST_BASE_URL}/api/v3/klines?"
            f"symbol={exch_symbol}&interval={tf_str}&startTime={start_ms}&endTime={end_ms}&limit={limit}"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
            loop = asyncio.get_running_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10.0, context=_get_ssl_context()).read()
            )
            raw_klines = json.loads(resp_data.decode("utf-8"))

            received_at = datetime.now(timezone.utc)
            publication_cutoff = min(end_time, received_at)
            candles: List[Candle] = []
            for item in raw_klines:
                open_ts = datetime.fromtimestamp(item[0] / 1000.0, tz=timezone.utc)
                close_ts = datetime.fromtimestamp(item[6] / 1000.0, tz=timezone.utc)
                candles.append(
                    Candle(
                        exchange=self.exchange_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        open_time=open_ts,
                        close_time=close_ts,
                        open_price=Decimal(str(item[1])),
                        high_price=Decimal(str(item[2])),
                        low_price=Decimal(str(item[3])),
                        close_price=Decimal(str(item[4])),
                        volume=Decimal(str(item[5])),
                        quote_volume=Decimal(str(item[7])),
                        trades_count=int(item[8]),
                        exchange_timestamp=close_ts,
                        is_closed=close_ts + timedelta(milliseconds=1) <= publication_cutoff,
                        data_quality_status=DataQualityStatus.HEALTHY
                    )
                )
            return candles
        except Exception as e:
            logger.error("Binance public fetch_candles error", extra={"symbol": symbol, "error": str(e)})
            raise e

    async def fetch_current_prices(self, symbols: Sequence[str]) -> Dict[str, Decimal]:
        """Fetches the latest traded price for each symbol from Binance's public REST API
        (GET /api/v3/ticker/price). Public endpoint only, no API key."""
        exch_symbols = [symbol_registry.to_exchange_symbol(s) for s in symbols]
        symbols_param = urllib.parse.quote(json.dumps(exch_symbols, separators=(",", ":")))
        url = f"{self.REST_BASE_URL}/api/v3/ticker/price?symbols={symbols_param}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
            loop = asyncio.get_running_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10.0, context=_get_ssl_context()).read()
            )
            raw = json.loads(resp_data.decode("utf-8"))

            exch_to_canonical = dict(zip(exch_symbols, symbols, strict=True))
            prices: Dict[str, Decimal] = {}
            for item in raw:
                canonical = exch_to_canonical.get(item["symbol"])
                if canonical:
                    prices[canonical] = Decimal(str(item["price"]))
            return prices
        except Exception as e:
            logger.error("Binance public fetch_current_prices error", extra={"symbols": list(symbols), "error": str(e)})
            raise e

    async def fetch_order_book_snapshot(
        self,
        symbol: str,
        depth: int = 100,
    ) -> OrderBookSnapshot:
        """Fetches public order book snapshot from Binance public REST API."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        url = f"{self.REST_BASE_URL}/api/v3/depth?symbol={exch_symbol}&limit={depth}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
            loop = asyncio.get_running_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10.0, context=_get_ssl_context()).read()
            )
            raw_depth = json.loads(resp_data.decode("utf-8"))

            now = datetime.now(timezone.utc)
            bids = [
                OrderBookLevel(price=Decimal(str(p)), quantity=Decimal(str(q)))
                for p, q in raw_depth.get("bids", [])
            ]
            asks = [
                OrderBookLevel(price=Decimal(str(p)), quantity=Decimal(str(q)))
                for p, q in raw_depth.get("asks", [])
            ]

            return OrderBookSnapshot(
                exchange=self.exchange_id,
                symbol=symbol,
                sequence_id=int(raw_depth.get("lastUpdateId", 0)),
                bids=bids,
                asks=asks,
                exchange_timestamp=now
            )
        except Exception as e:
            logger.error("Binance public fetch_order_book_snapshot error", extra={"symbol": symbol, "error": str(e)})
            raise e

    async def stream_trades(self, symbols: Sequence[str]) -> AsyncIterator[MarketTrade]:
        if False:
            yield MarketTrade(...)

    async def stream_candles(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[Timeframe],
    ) -> AsyncIterator[CandleUpdate]:
        if False:
            yield CandleUpdate(...)

    async def stream_order_book(self, symbols: Sequence[str]) -> AsyncIterator[OrderBookDelta]:
        if False:
            yield OrderBookDelta(...)
