# Alpha Research Campaign

Runs the platform's real production backtest pipeline (`packages/backtest/engine.py` +
`packages/governance/decision_service.py`) across multi-year real market data and a curated
grid of strategy configurations, and only publishes a strategy configuration as "evidence" if
it clears an explicit, pre-declared promotion gate on out-of-sample data.

## Layout

- `packages/research/data_fetcher.py` — pulls real multi-year Binance daily OHLCV from the
  public data mirror (`data-api.binance.vision`), cached locally under `data/research/`
  (gitignored, regenerable — re-run to refresh).
- `packages/research/config_grid.py` — the controlled (non-factorial) set of strategy
  configuration variants under test, each with a stated hypothesis.
- `packages/research/gate.py` — the promotion gate implementation. See
  `ALPHA_RESEARCH_GATE.md` for the criteria and rationale.
- `packages/research/campaign.py` — orchestrator: walk-forward fold generation, parallel
  execution across a process pool, full experiment ledger, gate evaluation, evidence
  publishing.

## Running

```
python -m packages.research.campaign [num_worker_processes]
```

Outputs (this directory):

- `experiments/EXPERIMENT_LEDGER.csv` — every single experiment run, pass or fail. Nothing is
  filtered out of this file.
- `experiments/GATE_RESULTS.csv` — one row per (symbol, config) pair with the aggregated
  out-of-sample gate verdict.
- `experiments/CAMPAIGN_MANIFEST.json` — run-level provenance: git SHA, data range, worker
  count, elapsed time, total experiment count.
- `../ALPHA_RESEARCH_CAMPAIGN_EVIDENCE.md` — published evidence for configs that cleared the
  gate on every symbol tested, or an explicit "no strategy cleared the gate" report if none did.

## Result of the most recent campaign run

See `../ALPHA_RESEARCH_CAMPAIGN_EVIDENCE.md` and `experiments/CAMPAIGN_MANIFEST.json` for the
actual, current result — this file is not a substitute for those and is not updated per run.
