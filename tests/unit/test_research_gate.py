"""packages/research/gate.py -- the promotion gate's fixed-threshold criteria (evaluate_gate)
and the second-layer, downgrade-only overfitting controls (apply_overfitting_controls) that
sit on top of it, using the real Deflated Sharpe Ratio / Probability of Backtest Overfitting
implementations in packages/research/overfitting.py."""

from decimal import Decimal
from typing import List, Optional

from packages.research.gate import DEFAULT_GATE, FoldResult, apply_overfitting_controls, evaluate_gate


def _fold(number: int, trades: int, net_profit: str, sharpe: Optional[str], dd: str = "5.0") -> FoldResult:
    return FoldResult(
        fold_number=number, test_start="2026-01-01", test_end="2026-01-31", trades=trades,
        net_profit=Decimal(net_profit), total_return_pct=Decimal("1.0"),
        sharpe_ratio=Decimal(sharpe) if sharpe is not None else None, max_drawdown_pct=Decimal(dd),
    )


def _strong_folds(n: int = 3) -> List[FoldResult]:
    return [_fold(i + 1, trades=10, net_profit="500", sharpe="1.5") for i in range(n)]


# --------------------------------------------------------------------------------------
# evaluate_gate (fixed-threshold criteria)
# --------------------------------------------------------------------------------------


def test_evaluate_gate_passes_a_clean_strong_result():
    result = evaluate_gate("BTC/USDT", "cfg_a", "hash_a", _strong_folds())
    assert result.passed is True
    assert result.reasons == []
    assert result.total_oos_trades == 30


def test_evaluate_gate_fails_below_min_oos_trades():
    folds = [_fold(1, trades=1, net_profit="10", sharpe="1.5")]
    result = evaluate_gate("BTC/USDT", "cfg_b", "hash_b", folds)
    assert result.passed is False
    assert any("TOTAL_OOS_TRADES_BELOW_MIN" in r for r in result.reasons)


def test_evaluate_gate_fails_negative_aggregate_pnl():
    folds = [_fold(i + 1, trades=10, net_profit="-100", sharpe="1.5") for i in range(3)]
    result = evaluate_gate("BTC/USDT", "cfg_c", "hash_c", folds)
    assert result.passed is False
    assert any("AGGREGATE_NET_PNL_NOT_POSITIVE" in r for r in result.reasons)


# --------------------------------------------------------------------------------------
# apply_overfitting_controls (second layer, downgrade-only)
# --------------------------------------------------------------------------------------


def test_overfitting_controls_never_promote_an_already_failed_result():
    failed = evaluate_gate("BTC/USDT", "cfg_fail", "hash", [_fold(1, trades=1, net_profit="-10", sharpe=None)])
    assert failed.passed is False

    fold_sharpes = {"cfg_fail": [-1.0, -1.0, -1.0], "cfg_other": [1.0, 1.0, 1.0]}
    updated = apply_overfitting_controls([failed], fold_sharpes)
    assert updated[0].passed is False


def test_overfitting_controls_keep_a_passed_result_when_dsr_and_pbo_are_healthy():
    passed = evaluate_gate("BTC/USDT", "cfg_strong", "hash", _strong_folds())
    assert passed.passed is True

    # Only a handful of trials, and cfg_strong consistently dominates across every fold (not
    # just on average) -- a low-overfitting-risk scenario: DSR should clear the default 0.95
    # threshold and PBO should stay at 0 (the best in-sample trial is also the best OOS in
    # every partition, so CSCV never catches it "switching winners").
    fold_sharpes = {
        "cfg_strong": [1.5, 1.6, 1.4],
        "cfg_b": [0.5, 0.6, 0.4],
        "cfg_c": [0.3, 0.2, 0.35],
    }
    updated = apply_overfitting_controls([passed], fold_sharpes)
    result = updated[0]
    assert result.deflated_sharpe_ratio is not None
    assert result.probability_of_backtest_overfitting is not None
    assert result.passed is True
    assert result.reasons == []


def test_overfitting_controls_downgrade_a_passed_result_with_many_trials_and_weak_signal():
    # A borderline-passing result (mean sharpe just above the 0.5 min, 21 OOS trades - clears
    # min_total_oos_trades=20) becomes suspect once placed against a config grid with dozens
    # of noisy trials -- DSR should fail it even though evaluate_gate's fixed thresholds alone
    # did not.
    borderline_folds = [_fold(i + 1, trades=7, net_profit="10", sharpe="0.55") for i in range(3)]
    passed = evaluate_gate("BTC/USDT", "cfg_borderline", "hash", borderline_folds)
    assert passed.passed is True

    fold_sharpes = {f"cfg_{i}": [0.5 + 0.3 * ((-1) ** i), -0.2, 0.1] for i in range(40)}
    fold_sharpes["cfg_borderline"] = [0.55, 0.55, 0.55]

    updated = apply_overfitting_controls([passed], fold_sharpes)
    result = updated[0]
    assert result.multiple_testing_warning is not None
    assert result.deflated_sharpe_ratio is not None
    assert result.deflated_sharpe_ratio < Decimal("0.95")
    assert result.passed is False
    assert any("DEFLATED_SHARPE_RATIO_BELOW_MIN" in r for r in result.reasons)


def test_overfitting_controls_no_op_when_no_trial_context_supplied():
    passed = evaluate_gate("BTC/USDT", "cfg_x", "hash", _strong_folds())
    updated = apply_overfitting_controls([passed], {})
    assert updated == [passed]


def test_promotion_gate_default_thresholds_are_reasonably_conservative():
    assert DEFAULT_GATE.min_deflated_sharpe_ratio == Decimal("0.95")
    assert DEFAULT_GATE.max_probability_of_backtest_overfitting == Decimal("0.5")
