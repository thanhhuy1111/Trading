# IMPLEMENTATION SUMMARY

| Finding | Code change | Test | Status |
|---|---|---|---|
| F-01 | New `packages/governance/decision_service.py` (real features→regime→agents→critic→consensus→allocator, no DB). `packages/paper/pipeline.py` rewritten to call it; fabricated intent (regime=TREND_UP, conf=0.85, net_edge=120, random signal IDs) removed. | `tests/unit/test_decision_pipeline_e2e.py`, `tests/unit/test_pipeline_wiring.py` | IMPLEMENTED+VERIFIED (paper). Backtest rewire OPEN. |
| F-01 (agents) | Removed hardcoded `reference_price=65000` from `trend.py`/`reversion.py`/`breakout.py`/`allocator.py`; agents read `reference_price` + `StrategyConfig` from context (`packages/agents/pricing.py`, `packages/agents/strategy_config.py`). | `test_pipeline_wiring.test_no_hardcoded_reference_price_in_agents_or_allocator` | VERIFIED |
| F-01 (honest edge) | `critic.py`/`consensus.py` default missing expected return to **0 bps** (+ `EXPECTED_RETURN_UNAVAILABLE`), not 50. Allocator NO_TRADE when no real edge/reference. Agents emit a transparent TP-distance×confidence proxy. | e2e test asserts `expected_return_bps>0` only from real levels; `test_governance_safety` | VERIFIED |
| F-03 | `ExitProtector.evaluate_position_exit` accepts `owner_position_manager`; paper passes its session manager (no forced global write). | full unit suite | PARTIAL (durable per-session ledger still pending) |
| F-06 | Paper entry validated by `execution_validation_gate` before fill. | paper path exercised in suite | PARTIAL |
| F-08 | `paper/adapter.py` models slippage vs. `reference_price` (5 bps), not clamped to limit. | `test_execution_entry_cap.test_buy_fill_never_exceeds... / test_sell_fill_has_slippage...` | VERIFIED |
| F-09 | Paper BUY fill `min(raw, limit, maximum_entry_price)`; added optional `reference_price` to `ExchangeOrderRequest`. | `test_execution_entry_cap` | VERIFIED |
| F-13 | `risk/governor.py` resolves `current_time = eval_time` before any comparison. | governor tests | VERIFIED |
| F-14 | `features/calculators/momentum.py` Wilder-smoothed RSI. | `test_feature_calculators.test_rsi_calculator_bounded` | VERIFIED |
| F-02, F-04, F-05, F-07, F-10, F-11, F-12 | Not implemented this pass. | — | OPEN (see REMAINING_LIMITATIONS) |

## New / changed files
- New: `packages/agents/strategy_config.py`, `packages/agents/pricing.py`, `packages/governance/decision_service.py`, `tests/unit/test_decision_pipeline_e2e.py`, `tests/unit/test_pipeline_wiring.py`, `tests/unit/test_execution_entry_cap.py`.
- Changed: `packages/agents/{models,trend,reversion,breakout,regime}.py`, `packages/governance/{critic,consensus,allocator}.py`, `packages/paper/{pipeline,adapter}.py`, `packages/positions/exit_protector.py`, `packages/risk/governor.py`, `packages/execution/models.py`, `packages/features/calculators/momentum.py`.
