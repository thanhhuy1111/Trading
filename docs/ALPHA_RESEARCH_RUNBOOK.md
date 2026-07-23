# ALPHA RESEARCH — RUNBOOK

## 1. Setup

```bash
pip install -e ".[dev,research]"
```

The `research` extra (`scikit-learn`, `pyarrow`, `pyyaml`, `scipy`) is training-time only
— never imported by runtime inference code (`packages/prediction/*`). See
`pyproject.toml`.

## 2. Full workflow

```bash
python -m packages.research.cli download-data --config configs/research/btc_eth_v1.yaml
python -m packages.research.cli build-dataset --config configs/research/btc_eth_v1.yaml
python -m packages.research.cli train-model   --config configs/research/btc_eth_v1.yaml --dataset-id <dataset_id>
python -m packages.research.cli run-walk-forward --config configs/research/btc_eth_v1.yaml \
    --dataset-id <dataset_id> --model-id <model_id>
python -m packages.research.cli publish-evidence --config configs/research/btc_eth_v1.yaml \
    --evaluation-id <evaluation_id> --strategy-name multi_agent_consensus_pipeline --strategy-version 1.0.0
python -m packages.research.cli list-models
python -m packages.research.cli list-evidence
```

Every subcommand prints the ID it produces (`dataset_id`, `model_id`, `evaluation_id`,
`evidence_id`) — copy it forward into the next command. `--dry-run` is supported on
`download-data`, `build-dataset`, `train-model`, `run-walk-forward`, `publish-evidence`
and touches neither disk nor the runtime registries.

`artifacts/` and `data/research/` are relative to the current working directory and are
gitignored; run every command from the same directory (typically the repo root) so
commands can find each other's output.

## 3. Example: a real bounded smoke run (executed during this phase's development)

This is the exact command sequence and result from a real, bounded run against live
Binance data (BTCUSDT, 1h, ~7 weeks, executed 2026-07-23) — reproduced here so the
runbook itself is grounded in a real execution, not a hypothetical:

```bash
python -m packages.research.cli download-data --config configs/research/smoke_test.yaml \
    --output data/research/candles
# Downloaded BTCUSDT/1h: 1177 candles cached under data/research/candles

python -m packages.research.cli build-dataset --config configs/research/smoke_test.yaml \
    --input data/research/candles
# Built dataset 8ec92cbf-f40e-49aa-ba6d-23fd23b68612: 1177 candles,
#   checksum=0df430e136b589ee..., status=VALIDATED, duplicates=0, rejected=0

python -m packages.research.cli train-model --config configs/research/smoke_test.yaml \
    --dataset-id 8ec92cbf-f40e-49aa-ba6d-23fd23b68612
# Trained model 9a1c08ec-a941-46da-a309-a08ff7217ee6 (logistic_regression logreg_smoke_v1),
#   checksum=4cc9b203fd925b0d...
# Train rows: 268, horizon_minutes=60

python -m packages.research.cli run-walk-forward --config configs/research/smoke_test.yaml \
    --dataset-id 8ec92cbf-f40e-49aa-ba6d-23fd23b68612 --model-id 9a1c08ec-a941-46da-a309-a08ff7217ee6
# [NO_TRADE] trades=0 net_pnl_bps=None
# [BUY_AND_HOLD] trades=188 net_pnl_bps=-4559.481703
# [TREND_ONLY] trades=36 net_pnl_bps=-965.496383
# [MEAN_REVERSION_ONLY] trades=6 net_pnl_bps=-189.486588
# [BREAKOUT_ONLY] trades=6 net_pnl_bps=-194.010902
# [MULTI_AGENT_NO_ML] trades=39 net_pnl_bps=-1028.749503
# [logreg_smoke_v1] trades=0 net_pnl_bps=None calibration_score=None

python -m packages.research.cli publish-evidence --config configs/research/smoke_test.yaml \
    --evaluation-id <MULTI_AGENT_NO_ML evaluation_id> \
    --strategy-name multi_agent_consensus_pipeline --strategy-version smoke_test_1.0.0
# Published evidence ...: status=REJECTED
#   reasons=['INSUFFICIENT_OOS_TRADE_COUNT', 'INSUFFICIENT_WALK_FORWARD_WINDOWS',
#            'PROFIT_FACTOR_BELOW_THRESHOLD', 'SHARPE_BELOW_THRESHOLD',
#            'NON_POSITIVE_EXPECTANCY']
```

**This REJECTED result is the correct, expected outcome for a 7-week smoke sample against
default production-scale gates (100+ OOS trades, 3+ walk-forward folds)** — not a bug, and
not evidence the pipeline is broken. Every baseline also lost money on real fees/spread/
slippage over this short, specific window; see the implementation report for the full
breakdown and explicit non-claim that this generalizes. **Do not approve a strategy based
on a smoke-scale run** — this is exactly the failure mode `configs/research/smoke_test.yaml`
exists to demonstrate is correctly blocked, not to produce a shippable result.

## 4. Interpreting `run-walk-forward` output

- `trades=0` for a baseline/model on the test split means it never decided to enter
  during that window — check `min_probability_profit`
  (`packages.recommendation.config.recommendation_config`, used as the model's decision
  threshold in `packages.research.cli._apply_model_predictions`) isn't set higher than
  the model's predicted probabilities ever reach for a genuinely undertrained model.
- `net_pnl_bps=None` means `trades=0` (there is nothing to sum).
- A negative `net_pnl_bps` after real fees/spread/slippage is a normal, informative
  result — it is what "the strategy loses money on this data after costs" looks like,
  not a formatting bug.

## 5. Running the offline test suite

```bash
pytest tests/unit -k research -q          # just the alpha research tests
pytest tests/unit -q                       # full repository suite (includes the above)
```

No network access or `GEMINI_API_KEY` required for any of the above.

## 6. Extending to a larger run

To move beyond a smoke run toward genuine evidence generation: widen `configs/research/
btc_eth_v1.yaml`'s date range to cover enough history that `num_folds x` (trades per
fold) clears `approval.min_oos_trades` with real margin, across BOTH configured symbols
and all three timeframes, and re-run the full sequence in §2. Expect this to take
materially longer than the smoke run (§3) purely due to Binance's public rate limits and
the O(n) agent-evaluation cost in `packages.research.baselines`
(`compute_baseline_decisions` runs 4 real agent/DecisionService evaluations per entry
point). This was not executed as part of this phase — see the implementation report's
remaining-gaps section for why, and what running it would take.
