"""GET /features/derivatives/definitions and /features/derivatives/snapshots/latest --
exercised entirely offline by monkeypatching the module-level `_derivatives_provider.fetch_snapshot`,
`_spot_provider.fetch_current_prices`, and the shared `derivatives_history.append_snapshot`/
`load_history` functions (redirected to a `tmp_path` cache dir), following the same convention
as tests/unit/test_market_data_derivatives_endpoint.py."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import apps.api.routers.features as features_router
from apps.api.main import app
from packages.market_data import derivatives_history as derivatives_history_module
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(
    ts: datetime,
    funding_rate: str = "0.0001",
    open_interest: str = "1000",
    futures_basis_bps: str = "10",
) -> DerivativesSnapshot:
    return DerivativesSnapshot(
        exchange="binance_usdm_futures",
        symbol=SYMBOL,
        exchange_timestamp=ts,
        data_quality_status=DataQualityStatus.HEALTHY,
        funding_rate=Decimal(funding_rate),
        open_interest=Decimal(open_interest),
        futures_basis_bps=Decimal(futures_basis_bps),
    )


def _patch_history_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirects both `append_snapshot`/`load_history` (as called from the router) to a
    `tmp_path` cache dir so tests never touch the real `data/research/derivatives/` cache."""
    real_append = derivatives_history_module.append_snapshot
    real_load = derivatives_history_module.load_history

    def _append(snapshot: DerivativesSnapshot, cache_dir: Path = tmp_path) -> bool:
        return real_append(snapshot, cache_dir=tmp_path)

    def _load(
        symbol: str, as_of: datetime, lookback: Optional[timedelta] = None, cache_dir: Path = tmp_path
    ) -> List[DerivativesSnapshot]:
        return real_load(symbol, as_of, lookback=lookback, cache_dir=tmp_path)

    monkeypatch.setattr(derivatives_history_module, "append_snapshot", _append)
    monkeypatch.setattr(derivatives_history_module, "load_history", _load)


def _patch_spot_price(monkeypatch: pytest.MonkeyPatch, price: Decimal) -> None:
    async def _fake_fetch_current_prices(symbols: List[str]) -> Dict[str, Decimal]:
        return {s: price for s in symbols}

    monkeypatch.setattr(features_router._spot_provider, "fetch_current_prices", _fake_fetch_current_prices)


def _patch_live_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot: DerivativesSnapshot) -> None:
    async def _fake_fetch_snapshot(symbol: str, spot_reference_price: Optional[Decimal] = None) -> DerivativesSnapshot:
        return snapshot

    monkeypatch.setattr(features_router._derivatives_provider, "fetch_snapshot", _fake_fetch_snapshot)


def test_derivatives_definitions_lists_three_registered_features() -> None:
    with TestClient(app) as client:
        response = client.get("/features/derivatives/definitions")
    assert response.status_code == 200
    names = {d["name"] for d in response.json()}
    assert {"funding_rate_zscore_20", "open_interest_roc_12", "futures_basis_momentum_6"} <= names


def test_latest_derivatives_snapshot_is_warming_up_on_first_ever_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_history_cache(monkeypatch, tmp_path)
    _patch_spot_price(monkeypatch, Decimal("50000"))
    _patch_live_snapshot(monkeypatch, _snapshot(BASE_TIME))

    with TestClient(app) as client:
        response = client.get(f"/features/derivatives/snapshots/latest?symbol={SYMBOL}")
    assert response.status_code == 200
    body: Dict[str, Any] = response.json()
    assert body["quality_status"] == "WARMING_UP"
    assert all(v is None for v in body["values"].values())


def test_latest_derivatives_snapshot_computes_real_values_once_enough_history_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_history_cache(monkeypatch, tmp_path)
    _patch_spot_price(monkeypatch, Decimal("50000"))

    # Pre-seed 24 real historical polls, 5 minutes apart -- enough for every calculator's
    # required_lookback (max 20, for funding_rate_zscore_20) once the live fetch adds one more.
    for i in range(24):
        derivatives_history_module.append_snapshot(
            _snapshot(BASE_TIME + timedelta(minutes=5 * i)), cache_dir=tmp_path
        )

    live_ts = BASE_TIME + timedelta(minutes=5 * 24)
    _patch_live_snapshot(monkeypatch, _snapshot(live_ts, funding_rate="0.0009"))

    with TestClient(app) as client:
        response = client.get(f"/features/derivatives/snapshots/latest?symbol={SYMBOL}")
    assert response.status_code == 200
    body: Dict[str, Any] = response.json()
    assert body["quality_status"] == "VALID"
    assert body["values"]["funding_rate_zscore_20"] is not None
    assert body["values"]["open_interest_roc_12"] is not None
    assert body["values"]["futures_basis_momentum_6"] is not None
    assert body["lineage"]["sample_count"] == 25  # 24 seeded + the live fetch just appended
    assert body["quality_issues"] == []
