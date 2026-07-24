"""Campaign API contract tests with an offline public-candle adapter."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers.campaign import (
    AnalysisRunRequest,
    CampaignAPIError,
    get_research_analysis_runtime,
    run_analysis,
)
from packages.market_data.models import Candle, Timeframe
from packages.runtime.research_analysis import PublicResearchAnalysisRuntime

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _rising_candles(count: int = 80) -> list[Candle]:
    candles: list[Candle] = []
    price = Decimal("50000")
    for index in range(count):
        open_time = T0 + timedelta(hours=4 * index)
        close_time = open_time + timedelta(hours=4) - timedelta(milliseconds=1)
        next_price = price * Decimal("1.002")
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe=Timeframe.H4,
                open_time=open_time,
                close_time=close_time,
                exchange_timestamp=close_time,
                open_price=price,
                high_price=next_price + Decimal("20"),
                low_price=price - Decimal("20"),
                close_price=next_price,
                volume=Decimal("100"),
                trades_count=100,
                is_closed=True,
            )
        )
        price = next_price
    return candles


_CANDLES = _rising_candles()
_NOW = _CANDLES[-1].close_time + timedelta(minutes=1)


async def _fetch_candles(
    symbol: str,
    timeframe: Timeframe,
    start_time: datetime,
    end_time: datetime,
    limit: int,
) -> Sequence[Candle]:
    del start_time, end_time, limit
    if symbol != "BTC/USDT" or timeframe != Timeframe.H4:
        return []
    return _CANDLES


@pytest.fixture(autouse=True)
def _offline_runtime() -> None:
    runtime = PublicResearchAnalysisRuntime(
        fetch_candles=_fetch_candles,
        clock=lambda: _NOW,
    )
    app.dependency_overrides[get_research_analysis_runtime] = lambda: runtime
    yield
    app.dependency_overrides.pop(get_research_analysis_runtime, None)


def test_phase10_routes_run_real_research_analysis_and_remain_non_actionable() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analysis/run",
            json={"symbol": "BTC/USDT", "timeframe": "4h", "request_id": "api-research-test"},
        )
        assert response.status_code == 202
        analysis = response.json()
        assert analysis["status"] == "AVAILABLE"
        assert analysis["runtime_mode"] == "RESEARCH_ONLY"
        assert datetime.fromisoformat(
            analysis["as_of_time"].replace("Z", "+00:00")
        ) == _CANDLES[-1].close_time + timedelta(milliseconds=1)
        assert analysis["recommendation"] in {"NO_DECISION", "RESEARCH_LONG"}
        assert len(analysis["evidence"]) == 13
        assert any(agent["agent_name"] == "regime_agent_v1" for agent in analysis["agents"])
        assert any(agent["status"] == "AVAILABLE" for agent in analysis["agents"])
        assert analysis["verification"]["decision"] == "NOT_RUN"
        assert analysis["risk"]["allow_trade"] is False
        assert analysis["risk"]["approved_quantity"] == "0"
        assert client.get("/api/v1/analysis/api-research-test").status_code == 200
        assert client.get("/api/v1/analysis/api-research-test/agents").json()["items"]
        assert client.get("/api/v1/analysis/api-research-test/debate").json()["data"]["status"] == "NOT_RUN"
        assert len(client.get("/api/v1/analysis/api-research-test/evidence").json()["items"]) == 13


def test_analysis_request_id_is_idempotent() -> None:
    payload = {"symbol": "BTC/USDT", "timeframe": "4h", "request_id": "api-idempotent-test"}
    with TestClient(app) as client:
        first = client.post("/api/v1/analysis/run", json=payload)
        second = client.post("/api/v1/analysis/run", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()

    conflict = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "request_id": "api-idempotent-test",
    }
    with TestClient(app) as client:
        mismatch = client.post("/api/v1/analysis/run", json=conflict)
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "ANALYSIS_REQUEST_ID_CONFLICT"


async def test_concurrent_matching_request_ids_share_one_runtime_call() -> None:
    class SlowRuntime(PublicResearchAnalysisRuntime):
        def __init__(self) -> None:
            super().__init__(fetch_candles=_fetch_candles, clock=lambda: _NOW)
            self.calls = 0

        async def analyze(
            self,
            *,
            analysis_id: str,
            symbol: str,
            timeframe: Timeframe,
        ):
            self.calls += 1
            await asyncio.sleep(0.05)
            return await super().analyze(
                analysis_id=analysis_id,
                symbol=symbol,
                timeframe=timeframe,
            )

    runtime = SlowRuntime()
    request = AnalysisRunRequest(
        symbol="BTC/USDT",
        timeframe="4h",
        request_id="api-concurrent-idempotent-test",
    )
    first, second = await asyncio.gather(
        run_analysis(request, runtime),
        run_analysis(request, runtime),
    )

    assert runtime.calls == 1
    assert first == second

    with pytest.raises(CampaignAPIError) as exc_info:
        await run_analysis(
            AnalysisRunRequest(
                symbol="BTC/USDT",
                timeframe="1h",
                request_id="api-concurrent-idempotent-test",
            ),
            runtime,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ANALYSIS_REQUEST_ID_CONFLICT"


async def test_cancelled_follower_does_not_poison_shared_analysis() -> None:
    class GatedRuntime(PublicResearchAnalysisRuntime):
        def __init__(self) -> None:
            super().__init__(fetch_candles=_fetch_candles, clock=lambda: _NOW)
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(
            self,
            *,
            analysis_id: str,
            symbol: str,
            timeframe: Timeframe,
        ):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return await super().analyze(
                analysis_id=analysis_id,
                symbol=symbol,
                timeframe=timeframe,
            )

    runtime = GatedRuntime()
    request = AnalysisRunRequest(
        symbol="BTC/USDT",
        timeframe="4h",
        request_id="api-cancelled-follower-test",
    )
    owner = asyncio.create_task(run_analysis(request, runtime))
    await runtime.started.wait()
    cancelled_follower = asyncio.create_task(run_analysis(request, runtime))
    surviving_follower = asyncio.create_task(run_analysis(request, runtime))
    await asyncio.sleep(0)

    cancelled_follower.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_follower

    runtime.release.set()
    owner_result, follower_result = await asyncio.gather(
        owner,
        surviving_follower,
    )

    assert runtime.calls == 1
    assert owner_result == follower_result


def test_market_prediction_health_and_error_contracts() -> None:
    with TestClient(app) as client:
        for suffix in ("overview", "candles", "features", "derivatives"):
            response = client.get(f"/api/v1/market/BTCUSDT/{suffix}")
            assert response.status_code == 200
            assert response.json()["status"] == "UNAVAILABLE"
        assert client.get("/api/v1/predictions").json()["items"] == []
        missing = client.get("/api/v1/predictions/missing")
        assert missing.status_code == 404
        assert missing.json()["error_code"] == "PREDICTION_NOT_FOUND"
        health = client.get("/api/v1/system/health").json()
        assert health["analysis_runtime"] == "RESEARCH_ONLY"
        assert "QUANTITATIVE_RUNTIME_NOT_BOUND" in health["reason_codes"]
        assert "NO_APPROVED_MODEL" not in health["reason_codes"]
        assert health["live_trading_enabled"] is False
        assert health["private_exchange_api_enabled"] is False


def test_analysis_scope_and_payload_fail_closed() -> None:
    with TestClient(app) as client:
        unsupported = client.post(
            "/api/v1/analysis/run",
            json={"symbol": "SOL/USDT", "timeframe": "4h"},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["error_code"] == "ANALYSIS_SCOPE_UNSUPPORTED"
        assert client.post(
            "/api/v1/analysis/run",
            json={"symbol": "BTC/USDT", "timeframe": "2h"},
        ).status_code == 422
        assert client.post(
            "/api/v1/analysis/run",
            json={"symbol": "BTC/USDT", "timeframe": "4h", "secret": "x"},
        ).status_code == 422
