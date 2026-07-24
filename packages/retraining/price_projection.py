"""Evidence-gated price-projection models for the dashboard chart.

One independent Ridge regression per forward horizon (1/3/6/12 bars), trained on real
historical candles and real point-in-time features, validated walk-forward out-of-sample
against the simplest possible baseline ("price doesn't change"). A horizon is only ever
approved -- and therefore only ever served, see apps/api/routers/market_data.py -- if it
demonstrably and CONSISTENTLY beats that baseline on held-out test folds it was never
fit on. This module can and does say no: see tests/unit/test_price_projection_training.py
for both a synthetic signal it correctly approves and pure random-walk noise it correctly
rejects.

Historical context: the chart previously showed a naive EMA-20-slope extrapolation. A real
walk-forward honesty check (scratchpad/backtest_projection.py) showed it has NO predictive
edge at any horizon -- worse MAPE than the naive baseline, ~50-54% directional accuracy
(a coin flip). This module replaces it with an actually-validated alternative, which may
just as validly conclude the same thing for a given symbol/timeframe -- that is a correct
outcome for this gate to produce, not a bug to work around.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from packages.backtest.models import WalkForwardFold
from packages.backtest.walk_forward import walk_forward_runner
from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.market_data.models import Candle, Timeframe

FEATURE_NAMES = ["ema_20_slope", "rsi_14", "return_3p", "atr_14", "volatility_20"]
HORIZONS = [1, 3, 6, 12]
ALPHA_GRID = [0.1, 1.0, 10.0]
MIN_RELATIVE_MAPE_IMPROVEMENT = 0.05  # OOS MAPE must be >= 5% relatively better than naive
MIN_DIRECTIONAL_ACCURACY = 0.55  # a small but real edge over the 50% coin-flip floor
NUM_FOLDS = 3
MIN_LOOKBACK_BARS = 25  # ema_20_slope needs ~20 bars of real history to be non-None

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "data" / "research" / "price_models"


@dataclass
class Row:
    as_of_time: datetime
    close_price: float
    features: List[float]
    # forward log-return per horizon; None where there isn't enough forward history yet.
    forward_returns: Dict[int, Optional[float]]


@dataclass
class HorizonResult:
    horizon: int
    approved: bool
    reason: str
    oos_mape: Optional[float] = None
    naive_oos_mape: Optional[float] = None
    oos_directional_accuracy: Optional[float] = None
    oos_trades: int = 0
    coefficients: Optional[List[float]] = None
    intercept: Optional[float] = None
    # StandardScaler params fit on TRAIN data only (never val/test/live data) -- inference
    # must scale raw live features the same way before applying coefficients/intercept, or
    # the fitted weights (which are only meaningful in scaled space) are silently wrong.
    feature_mean: Optional[List[float]] = None
    feature_scale: Optional[List[float]] = None


@dataclass
class TrainingResult:
    symbol: str
    timeframe: str
    trained_at: datetime
    dataset_checksum: str
    code_commit: str
    feature_names: List[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    horizons: Dict[int, HorizonResult] = field(default_factory=dict)


def _checksum_candles(candles: Sequence[Candle]) -> str:
    hasher = hashlib.sha256()
    for c in candles:
        hasher.update(f"{c.close_time.isoformat()}:{c.close_price}".encode("utf-8"))
    return hasher.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "UNKNOWN"


def build_rows(candles: Sequence[Candle], symbol: str, timeframe: Timeframe) -> List[Row]:
    """Point-in-time features (packages.features.pipeline.feature_pipeline.compute, the
    same pipeline every other agent/service in this repo uses) + real forward log-returns.
    A row missing any feature, or without enough forward history for a given horizon, never
    gets a guessed/imputed value -- it's skipped for that horizon (or entirely, if no
    feature is available at all)."""
    sorted_candles = sorted(candles, key=lambda c: c.open_time)
    rows: List[Row] = []
    for i in range(MIN_LOOKBACK_BARS, len(sorted_candles)):
        current = sorted_candles[i]
        history = sorted_candles[: i + 1]
        request = FeatureComputationRequest(
            exchange="binance", symbol=symbol, timeframe=timeframe,
            feature_set="standard_v1", as_of_time=current.close_time,
        )
        snapshot = feature_pipeline.compute(request, history)
        raw = [snapshot.values.get(name) for name in FEATURE_NAMES]
        if any(v is None for v in raw):
            continue
        features = [float(v) for v in raw]  # type: ignore[arg-type]

        forward_returns: Dict[int, Optional[float]] = {}
        for h in HORIZONS:
            if i + h < len(sorted_candles):
                future_close = sorted_candles[i + h].close_price
                forward_returns[h] = math.log(float(future_close) / float(current.close_price))
            else:
                forward_returns[h] = None
        rows.append(Row(
            as_of_time=current.close_time, close_price=float(current.close_price),
            features=features, forward_returns=forward_returns,
        ))
    return rows


def _fit_scaled_ridge(X: List[List[float]], y: List[float], alpha: float) -> Any:
    """Standardizes features (zero mean, unit variance, fit on X only) before fitting Ridge.
    Required, not cosmetic: this repo's real features span wildly different raw scales
    (e.g. rsi_14 ~0-100 vs ema_20_slope ~1e-4) -- Ridge's L2 penalty is scale-sensitive, so
    without standardizing first it penalizes small-scale-but-genuinely-informative features
    far more than large-scale ones, which was measured to suppress a real, constructed
    signal in tests/unit/test_price_projection_training.py during development."""
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(np.array(X))
    model = Ridge(alpha=alpha)
    model.fit(X_scaled, np.array(y))
    return scaler, model


def _predict(scaler: Any, model: Any, rows: List[Row]) -> List[float]:
    import numpy as np

    X_scaled = scaler.transform(np.array([r.features for r in rows]))
    result: List[float] = model.predict(X_scaled).tolist()
    return result


def _price_mape(rows: List[Row], predicted_log_returns: Sequence[float], horizon: int) -> float:
    errs = []
    for row, pred_ret in zip(rows, predicted_log_returns, strict=True):
        actual_ret = row.forward_returns[horizon]
        assert actual_ret is not None
        actual_price = row.close_price * math.exp(actual_ret)
        predicted_price = row.close_price * math.exp(pred_ret)
        errs.append(abs(predicted_price - actual_price) / actual_price)
    return sum(errs) / len(errs)


def _naive_price_mape(rows: List[Row], horizon: int) -> float:
    """The baseline every horizon must beat: predicted_price = last known close (i.e.
    predicted_log_return = 0)."""
    return _price_mape(rows, [0.0] * len(rows), horizon)


def _directional_accuracy(rows: List[Row], predicted_log_returns: Sequence[float], horizon: int) -> tuple[float, int]:
    correct = 0
    total = 0
    for row, pred_ret in zip(rows, predicted_log_returns, strict=True):
        actual_ret = row.forward_returns[horizon]
        assert actual_ret is not None
        actual_dir = 1 if actual_ret > 0 else (-1 if actual_ret < 0 else 0)
        pred_dir = 1 if pred_ret > 0 else (-1 if pred_ret < 0 else 0)
        if actual_dir == 0 or pred_dir == 0:
            continue
        total += 1
        if actual_dir == pred_dir:
            correct += 1
    return (correct / total if total else float("nan")), total


def evaluate_horizon(rows: List[Row], horizon: int, folds: List[WalkForwardFold]) -> HorizonResult:
    """Walk-forward evaluation: fit on each fold's TRAIN window, pick alpha by VALIDATION
    MAPE, measure the real, never-seen-during-fitting TEST window only. A horizon is
    approved only if OOS MAPE beats naive by >= MIN_RELATIVE_MAPE_IMPROVEMENT, directional
    accuracy clears MIN_DIRECTIONAL_ACCURACY, AND every individual fold independently beats
    naive -- one lucky fold carrying the average is exactly the overfitting failure mode
    this guards against (same philosophy as packages.research.gate.PromotionGate's
    min_profitable_fold_ratio)."""
    fold_test_mapes: List[float] = []
    fold_naive_mapes: List[float] = []
    fold_dir_correct = 0
    fold_dir_total = 0
    last_alpha: Optional[float] = None

    def _rows_in(start: datetime, end: datetime, inclusive_end: bool = False) -> List[Row]:
        out = []
        for r in rows:
            if r.forward_returns[horizon] is None:
                continue
            in_range = start <= r.as_of_time <= end if inclusive_end else start <= r.as_of_time < end
            if in_range:
                out.append(r)
        return out

    def _fit(train: List[Row], alpha: float) -> Any:
        X = [r.features for r in train]
        y = [r.forward_returns[horizon] for r in train]
        return _fit_scaled_ridge(X, y, alpha)  # type: ignore[arg-type]

    for fold in folds:
        train_rows = _rows_in(fold.train_start, fold.train_end)
        val_rows = _rows_in(fold.validation_start, fold.validation_end)
        test_rows = _rows_in(fold.test_start, fold.test_end, inclusive_end=True)
        if len(train_rows) < 10 or not val_rows or not test_rows:
            continue  # not enough real data in this fold for this horizon -- skip, don't fabricate

        best_alpha, best_val_mape = ALPHA_GRID[0], None
        for alpha in ALPHA_GRID:
            scaler, model = _fit(train_rows, alpha)
            val_preds = _predict(scaler, model, val_rows)
            val_mape = _price_mape(val_rows, val_preds, horizon)
            if best_val_mape is None or val_mape < best_val_mape:
                best_alpha, best_val_mape = alpha, val_mape

        scaler, model = _fit(train_rows, best_alpha)
        test_preds = _predict(scaler, model, test_rows)
        fold_test_mapes.append(_price_mape(test_rows, test_preds, horizon))
        fold_naive_mapes.append(_naive_price_mape(test_rows, horizon))
        dir_acc, dir_n = _directional_accuracy(test_rows, test_preds, horizon)
        if dir_n:
            fold_dir_correct += round(dir_acc * dir_n)
            fold_dir_total += dir_n
        last_alpha = best_alpha

    if not fold_test_mapes:
        return HorizonResult(horizon=horizon, approved=False, reason="INSUFFICIENT_DATA")

    oos_mape = sum(fold_test_mapes) / len(fold_test_mapes)
    naive_oos_mape = sum(fold_naive_mapes) / len(fold_naive_mapes)
    oos_dir_acc = fold_dir_correct / fold_dir_total if fold_dir_total else float("nan")

    every_fold_beats_naive = all(t < n for t, n in zip(fold_test_mapes, fold_naive_mapes, strict=True))
    relative_improvement = (naive_oos_mape - oos_mape) / naive_oos_mape if naive_oos_mape > 0 else 0.0

    approved = (
        relative_improvement >= MIN_RELATIVE_MAPE_IMPROVEMENT
        and oos_dir_acc >= MIN_DIRECTIONAL_ACCURACY
        and every_fold_beats_naive
    )
    reason = "APPROVED" if approved else (
        "FAILED_EVERY_FOLD_MUST_BEAT_NAIVE" if not every_fold_beats_naive
        else "FAILED_MAPE_IMPROVEMENT" if relative_improvement < MIN_RELATIVE_MAPE_IMPROVEMENT
        else "FAILED_DIRECTIONAL_ACCURACY"
    )

    coefficients: Optional[List[float]] = None
    intercept: Optional[float] = None
    feature_mean: Optional[List[float]] = None
    feature_scale: Optional[List[float]] = None
    if approved:
        # Refit on ALL available data (most information, most recent) using the alpha the
        # most recent fold validated -- the walk-forward evaluation above proves the
        # METHOD generalizes; this is the artifact actually served at inference time.
        all_rows = [r for r in rows if r.forward_returns[horizon] is not None]
        final_scaler, final_model = _fit(all_rows, last_alpha or ALPHA_GRID[0])
        coefficients = [float(c) for c in final_model.coef_]
        intercept = float(final_model.intercept_)
        feature_mean = [float(m) for m in final_scaler.mean_]
        feature_scale = [float(s) for s in final_scaler.scale_]

    return HorizonResult(
        horizon=horizon, approved=approved, reason=reason, oos_mape=oos_mape, naive_oos_mape=naive_oos_mape,
        oos_directional_accuracy=oos_dir_acc, oos_trades=fold_dir_total, coefficients=coefficients,
        intercept=intercept, feature_mean=feature_mean, feature_scale=feature_scale,
    )


def train(candles: Sequence[Candle], symbol: str, timeframe: Timeframe) -> TrainingResult:
    rows = build_rows(candles, symbol, timeframe)
    sorted_candles = sorted(candles, key=lambda c: c.open_time)
    folds = walk_forward_runner.generate_folds(
        session_id=uuid4(), start_time=sorted_candles[0].open_time, end_time=sorted_candles[-1].close_time,
        num_folds=NUM_FOLDS, purge_hours=1, embargo_hours=1,
    )
    horizons = {h: evaluate_horizon(rows, h, folds) for h in HORIZONS}
    return TrainingResult(
        symbol=symbol, timeframe=timeframe.value, trained_at=datetime.now(timezone.utc),
        dataset_checksum=_checksum_candles(sorted_candles), code_commit=_git_sha(), horizons=horizons,
    )


def artifact_path(symbol: str, timeframe: Timeframe) -> Path:
    safe_symbol = symbol.replace("/", "")
    return ARTIFACT_DIR / f"{safe_symbol}_{timeframe.value}.json"


def write_artifact(result: TrainingResult) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifact_path(result.symbol, Timeframe(result.timeframe))
    payload = {
        "symbol": result.symbol, "timeframe": result.timeframe, "trained_at": result.trained_at.isoformat(),
        "dataset_checksum": result.dataset_checksum, "code_commit": result.code_commit,
        "feature_names": result.feature_names,
        "horizons": {
            str(h): {
                "approved": r.approved, "reason": r.reason, "oos_mape": r.oos_mape,
                "naive_oos_mape": r.naive_oos_mape, "oos_directional_accuracy": r.oos_directional_accuracy,
                "oos_trades": r.oos_trades, "coefficients": r.coefficients, "intercept": r.intercept,
                "feature_mean": r.feature_mean, "feature_scale": r.feature_scale,
            }
            for h, r in result.horizons.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


async def run_training_cli(symbol: str, timeframe: Timeframe, lookback_bars: int = 2000) -> Path:
    from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
    from packages.market_data.historical_quality import TIMEFRAME_INTERVAL

    provider = BinancePublicMarketDataProvider()
    end_time = datetime.now(timezone.utc)
    start_time = end_time - TIMEFRAME_INTERVAL[timeframe] * lookback_bars
    candles = await provider.fetch_candles(symbol, timeframe, start_time, end_time, limit=lookback_bars)
    result = train(candles, symbol, timeframe)
    path = write_artifact(result)
    print(f"[price_projection] trained {symbol} {timeframe.value} on {len(candles)} real candles")
    for h in HORIZONS:
        r = result.horizons[h]
        print(
            f"  horizon={h:>2} approved={r.approved!s:>5} reason={r.reason:<32} "
            f"oos_mape={r.oos_mape} naive_oos_mape={r.naive_oos_mape} "
            f"dir_acc={r.oos_directional_accuracy} n={r.oos_trades}"
        )
    print(f"[price_projection] artifact written: {path}")
    return path


if __name__ == "__main__":
    import asyncio
    import sys

    cli_symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    cli_timeframe = Timeframe(sys.argv[2]) if len(sys.argv) > 2 else Timeframe.H1
    asyncio.run(run_training_cli(cli_symbol, cli_timeframe))
