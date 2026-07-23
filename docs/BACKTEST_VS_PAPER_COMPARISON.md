# Backtest vs Paper Trading Comparison Specification

## 1. Overview
The Paper Comparison Service (`packages/paper/comparison.py`) evaluates real-time paper trading performance against historical backtest session baselines for identical strategy configurations.

---

## 2. Comparison Metrics

| Metric | Calculation Formula | Target Threshold |
|---|---|---|
| **NAV Divergence (`nav_diff_pct`)** | `((Paper_NAV - Backtest_NAV) / Backtest_NAV) * 100` | `< ±2.5%` |
| **Slippage Drift (`slippage_diff_bps`)** | `Realized_Paper_Slippage - Simulated_Backtest_Slippage` | `< 5.0 bps` |
| **Trade Count Delta (`trade_count_diff`)** | `Paper_Trade_Count - Backtest_Trade_Count` | `0` |
| **Win Rate Comparison** | `Paper_Win_Rate vs Backtest_Win_Rate` | `< ±5.0%` |

---

## 3. Storage Schema (`paper_backtest_comparisons`)
Stores automated comparison reports for performance auditing and strategy promotion readiness evaluation.
