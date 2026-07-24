"""Offline tests for the public-data deterministic research analysis runtime."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from packages.market_data.models import Candle, Timeframe
from packages.runtime.research_analysis import PublicResearchAnalysisRuntime

T0 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _candles(count: int = 80) -> list[Candle]:
    rows: list[Candle] = []
    price = Decimal("60000")
    for index in range(count):
        open_time = T0 + timedelta(hours=4 * index)
        close_time = open_time + timedelta(hours=4) - timedelta(milliseconds=1)
        next_price = price * Decimal("1.001")
        rows.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe=Timeframe.H4,
                open_time=open_time,
                close_time=close_time,
                exchange_timestamp=close_time,
                open_price=price,
                high_price=next_price + Decimal("25"),
                low_price=price - Decimal("25"),
                close_price=next_price,
                volume=Decimal("120"),
                trades_count=100,
                is_closed=True,
            )
        )
        price = next_price
    return rows


_ROWS = _candles()
_NOW = _ROWS[-1].close_time + timedelta(minutes=5)


async def _fetch(
    symbol: str,
    timeframe: Timeframe,
    start_time: datetime,
    end_time: datetime,
    limit: int,
) -> Sequence[Candle]:
    del start_time, end_time, limit
    if (symbol, timeframe) != ("BTC/USDT", Timeframe.H4):
        return []
    return _ROWS


async def test_runtime_produces_observed_evidence_and_never_trade_authority() -> None:
    result = await PublicResearchAnalysisRuntime(
        fetch_candles=_fetch,
        clock=lambda: _NOW,
    ).analyze(
        analysis_id="runtime-success",
        symbol="BTC/USDT",
        timeframe=Timeframe.H4,
    )

    assert result.status == "AVAILABLE"
    expected_as_of = _ROWS[-1].close_time + timedelta(milliseconds=1)
    assert result.as_of_time == expected_as_of
    assert len(result.evidence) == 13
    assert all(item["source_id"] == "binance_public_rest" for item in result.evidence)
    expected_available_at = expected_as_of.isoformat()
    assert all(item["available_at"] == expected_available_at for item in result.evidence)
    assert any(agent["agent_name"] == "regime_agent_v1" for agent in result.agents)
    evidence_available_times = [
        datetime.fromisoformat(str(item["available_at"])) for item in result.evidence
    ]
    agent_as_of_times = [
        datetime.fromisoformat(str(agent["as_of_time"]))
        for agent in result.agents
        if "as_of_time" in agent
    ]
    assert agent_as_of_times
    assert min(agent_as_of_times) >= max(evidence_available_times)
    assert all("expected_return_bps" not in agent for agent in result.agents)
    assert any(
        agent.get("return_proxy_type") == "TARGET_DISTANCE_HEURISTIC_PROXY"
        for agent in result.agents
    )
    quantitative = next(
        agent for agent in result.agents if agent["agent_name"] == "quantitative_agent"
    )
    assert quantitative["reason_codes"] == ["QUANTITATIVE_RUNTIME_NOT_BOUND"]
    assert result.verification["decision"] == "NOT_RUN"
    assert result.risk["allow_trade"] is False
    assert result.risk["approved_quantity"] == "0"


async def test_future_candle_is_excluded_from_point_in_time_analysis() -> None:
    future = _ROWS[-1].model_copy(
        update={
            "open_time": _NOW + timedelta(hours=1),
            "close_time": _NOW + timedelta(hours=4),
            "exchange_timestamp": _NOW + timedelta(hours=4),
            "close_price": Decimal("999999"),
            "high_price": Decimal("1000000"),
        }
    )

    async def fetch_with_future(
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        del symbol, timeframe, start_time, end_time, limit
        return [*_ROWS, future]

    result = await PublicResearchAnalysisRuntime(
        fetch_candles=fetch_with_future,
        clock=lambda: _NOW,
    ).analyze(
        analysis_id="runtime-future",
        symbol="BTC/USDT",
        timeframe=Timeframe.H4,
    )

    assert result.status == "AVAILABLE"
    assert result.as_of_time == _ROWS[-1].close_time + timedelta(milliseconds=1)
    assert all(item["observed_at"] == _ROWS[-1].close_time.isoformat() for item in result.evidence)


async def test_missing_or_failed_public_data_is_safe_unavailable() -> None:
    async def empty_fetch(
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        del symbol, timeframe, start_time, end_time, limit
        return []

    async def failed_fetch(
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        del symbol, timeframe, start_time, end_time, limit
        raise RuntimeError("offline")

    empty = await PublicResearchAnalysisRuntime(
        fetch_candles=empty_fetch,
        clock=lambda: _NOW,
    ).analyze(analysis_id="empty", symbol="BTC/USDT", timeframe=Timeframe.H4)
    failed = await PublicResearchAnalysisRuntime(
        fetch_candles=failed_fetch,
        clock=lambda: _NOW,
    ).analyze(analysis_id="failed", symbol="BTC/USDT", timeframe=Timeframe.H4)

    assert empty.status == "UNAVAILABLE"
    assert empty.reason_codes == ("MARKET_DATA_QUALITY_REJECTED",)
    assert failed.status == "UNAVAILABLE"
    assert failed.reason_codes == ("PUBLIC_MARKET_DATA_UNAVAILABLE",)
    assert empty.evidence == failed.evidence == ()
    assert empty.risk["allow_trade"] is failed.risk["allow_trade"] is False


async def test_wrong_scope_and_short_history_fail_closed() -> None:
    wrong_scope = [_ROWS[0].model_copy(update={"symbol": "ETH/USDT"})]

    async def wrong_fetch(
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        del symbol, timeframe, start_time, end_time, limit
        return wrong_scope

    async def short_fetch(
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        del symbol, timeframe, start_time, end_time, limit
        return _ROWS[:20]

    wrong = await PublicResearchAnalysisRuntime(
        fetch_candles=wrong_fetch,
        clock=lambda: _NOW,
    ).analyze(analysis_id="wrong", symbol="BTC/USDT", timeframe=Timeframe.H4)
    short = await PublicResearchAnalysisRuntime(
        fetch_candles=short_fetch,
        clock=lambda: _ROWS[19].close_time + timedelta(minutes=1),
    ).analyze(analysis_id="short", symbol="BTC/USDT", timeframe=Timeframe.H4)

    assert wrong.reason_codes == ("MARKET_DATA_SCOPE_MISMATCH",)
    assert short.reason_codes == ("INSUFFICIENT_CANDLE_HISTORY",)


async def test_stale_market_data_fails_closed() -> None:
    stale = await PublicResearchAnalysisRuntime(
        fetch_candles=_fetch,
        clock=lambda: _NOW + timedelta(days=2),
    ).analyze(
        analysis_id="stale",
        symbol="BTC/USDT",
        timeframe=Timeframe.H4,
    )

    assert stale.status == "UNAVAILABLE"
    assert stale.reason_codes == ("MARKET_DATA_STALE",)
    assert stale.evidence == ()
