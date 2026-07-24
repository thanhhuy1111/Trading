# Campaign Final Acceptance Matrix

Date: 2026-07-24

Status: **PASSED WITH DECLARED ENVIRONMENT SKIPS**

## Data

| Requirement | Verified by |
|---|---|
| Spot ingestion | `tests/integration/test_binance_public_adapter.py` |
| Futures ingestion | `tests/unit/test_binance_futures_adapter.py` |
| Feature calculation | `tests/unit/test_feature_calculators.py`, `test_derivatives_calculators.py` |
| Availability lineage | `tests/unit/test_data_guardian.py`, XGBoost dataset tests |
| Evidence Registry | `tests/unit/test_evidence_exact_match.py`, advanced-agent tests |

## Quantitative

| Requirement | Verified by |
|---|---|
| Dataset build | `tests/unit/test_xgboost_dataset.py` |
| Training and walk-forward | `tests/unit/test_xgboost_training.py` |
| Approval | `tests/unit/test_xgboost_approval.py` |
| Artifact load and runtime prediction | `tests/unit/test_xgboost_runtime.py` |
| Fail-closed retraining workflow | `tests/unit/test_retraining_workflow.py` |

No real artifact is claimed approved by this test. The test verifies the gate and
`NO_APPROVED_MODEL` behavior.

## Multi-Agent

| Requirement | Verified by |
|---|---|
| Specialist analysis | `tests/unit/test_specialist_agents.py` |
| Bull–Bear debate | `tests/unit/test_debate.py` |
| Verification and risk | `tests/unit/test_verification_risk.py` |
| Manager | `tests/unit/test_manager_agent.py` |
| Advanced research agents | `tests/unit/test_advanced_agents.py` |

## Application

| Requirement | Verified by |
|---|---|
| API, prediction history, evidence, health | `tests/unit/test_campaign_api.py`, `test_health.py` |
| Dashboard views | Vitest: 2 files, 3 tests passed |
| Dashboard production build | TypeScript and Vite build passed |
| Dashboard dependency audit | `npm audit`: 0 vulnerabilities |

The production build emitted one non-blocking chunk-size warning for a 561.82 kB JavaScript
bundle.

## Operation

| Requirement | Verified by |
|---|---|
| Shadow scheduler and evaluation | `tests/unit/test_shadow_mode.py` |
| Paper portfolio | `tests/unit/test_paper_trading.py` |
| Experimental export | `tests/unit/test_experiments.py` |
| Thesis protocol and identity | `tests/unit/test_thesis_package.py` |
| Migration lifecycle | `tests/integration/test_db_migration.py` |

The 12 skipped tests are PostgreSQL durability drills that require an operator-provided
disposable `PAPER_DB_TEST_URL`. They are not silently converted to passes.

## Safe rejection

The selected acceptance run covers missing/stale/invalid market data, missing derivatives,
provider unavailable, invalid LLM schema, missing/future evidence, no approved model,
verification/risk rejection, wrong model version, duplicate work, and corrupted artifacts.
The deterministic end-to-end and rejection scenarios in
`tests/acceptance/test_final_acceptance.py` remain offline.

## Safety

- `LIVE_TRADING_ENABLED=False`.
- `PRIVATE_EXCHANGE_API_ENABLED=False`.
- `FEATURE_FLAGS_LIVE_TRADING=False`.
- All eight advanced feature flags default false.
- Tracked production-source secret-pattern scan returned no credential material.
- Private/order-path scan found only disabled adapters, simulators, paper execution, safety
  text and false-valued status fields.
- No private exchange request or real order submission was performed.
- No market record, evidence, probability, confidence, approval, thesis result, sample size,
  p-value, or significance was fabricated.

## Executed results

| Check | Result |
|---|---|
| Campaign-selected Python acceptance matrix | 207 passed |
| Full Python suite | 622 passed, 12 skipped, 0 failed |
| Phase 15 focused suite | 16 passed |
| Ruff | clean |
| Targeted Phase 15 mypy | clean |
| Full mypy | 202 errors in 71 files |
| Dashboard Vitest | 3 passed |
| Dashboard build | passed, one chunk-size warning |
| Dashboard audit | 0 vulnerabilities |
| Alembic 001/002 lifecycle | passed |
| `uv lock --check` | passed |

The full mypy debt is not hidden. It predates or accumulated outside the final documentation
and migration acceptance fix and remains backlog.
