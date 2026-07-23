# ALPHA RESEARCH — EVIDENCE POLICY

## 1. Calibration

`packages/research/calibration.py` fits Platt scaling (default) or isotonic regression on
**validation-split data only** — `fit_calibration` never sees test-split rows, and every
`CalibrationReport` records `fit_on: "validation_only"` for auditability. Method choice:
Platt below `ISOTONIC_SAMPLE_SIZE_THRESHOLD` (500) samples, isotonic above it — isotonic
regression can overfit its own calibration curve on small validation sets, so it is only
used once there is enough data for that not to matter.

Reuses the EXISTING `packages.prediction.calibration`/`packages.prediction.evaluation`
Brier score / expected calibration error (ECE) / log-loss / reliability-bucket functions
— no second metric implementation. `test_reliability_buckets_support_comparing_a_
probability_bucket_to_realized_frequency` proves a reported probability bucket (e.g.
"0.70") is directly comparable against the realized outcome frequency in that bucket, as
the implementation plan requires.

## 2. Multiple-testing / overfitting controls

`packages/research/overfitting.py::ExperimentTracker` records every model/hyperparameter/
feature-set/threshold combination actually evaluated, so `experiments_tried` on an
`EvaluationReport` is a real count. `run_walk_forward_evaluation` emits a
`multiple_testing_warning` once that count exceeds 20.

Two statistics are computed for real, not stubbed:

- **Deflated Sharpe Ratio (DSR)** — Bailey & Lopez de Prado (2014). Answers "what is the
  probability the observed Sharpe ratio is genuinely positive, after accounting for
  having tried N trials and for return skew/kurtosis?" When the standard deviation of
  Sharpe ratios across trials isn't tracked, it defaults to 1.0 — a standard, documented
  simplification also used by the original paper when the full trial distribution isn't
  retained.
- **Probability of Backtest Overfitting (PBO)** — combinatorially symmetric
  cross-validation (CSCV, Bailey et al. 2015) over a trials × walk-forward-fold
  performance matrix (built from the exact same `window` breakdowns
  `run_walk_forward_evaluation` already produces).

**Both are small-sample statistics.** With realistically only 2-5 walk-forward folds and
a handful of trials in any given research run, treat the numeric DSR/PBO values as
directional warnings, not precise probabilities — this is stated deliberately, not
softened for effect.

## 3. Approval status and gates

Status is decided in two layers, applied in order, and the second layer can only
**downgrade** an APPROVED result — never upgrade a REJECTED/INSUFFICIENT/STALE one to
APPROVED (`test_evaluate_research_approval_never_upgrades_a_rejected_result`).

**Layer 1 — the EXISTING policy, reused unchanged**
(`packages.recommendation.evidence_service.evaluate_approval`, already built and tested
before this phase):

| Gate | Default threshold |
|---|---|
| OOS trade count | ≥ 100 |
| Walk-forward windows | ≥ 3 |
| Profit factor | ≥ 1.20 |
| Sharpe (OOS) | ≥ 1.00 |
| Max drawdown | ≤ 20% |
| Expectancy | > 0 |
| Evidence age | ≤ 90 days (else `STALE`) |

**Layer 2 — research-specific additions** (`packages.research.evidence_publisher
.evaluate_research_approval`, this phase), applied only when layer 1 says `APPROVED`:

| Check | Config |
|---|---|
| No single walk-forward window contributes more than a configured share of total positive profit | `ApprovalGateConfig.max_single_window_profit_share` (default 0.60) |
| A calibration report exists and its `calibration_score` clears a threshold | `ApprovalGateConfig.min_calibration_score` (default 0.50) |

Failing either downgrades `APPROVED → RESEARCH_ONLY` — the strategy is still visible for
internal research, just not presented as production-ready.

## 4. Allowed statuses

```
APPROVED        Passed all gates. Only status that lets RecommendationService
                (via packages.research.runtime_loader.load_approved_model) load
                the corresponding model into the live prediction registry.
RESEARCH_ONLY   Positive-looking but short of a hard gate, or approved-but-
                concentrated/uncalibrated. Visible for research, never user-facing.
INSUFFICIENT    No OOS metrics recorded at all (e.g. nothing published yet for
                this strategy/version) -- the honest default for an unregistered
                strategy, never assumed-good.
REJECTED        Outright unprofitable (negative expectancy or profit factor < 1).
                A rejected strategy is a valid, complete research result.
STALE           Evidence older than the configured max age; re-evaluate before trusting.
```

**Gates are never loosened to manufacture an APPROVED result.** This is a policy
statement enforced by the code structure itself: there is no parameter, flag, or code
path in `packages/research/evidence_publisher.py` that widens a threshold based on a
desired outcome — thresholds come only from `ApprovalGateConfig`/`RecommendationConfig`,
set once per config file, before evaluation runs.

## 5. Runtime integration — the one-way gate

`packages.research.runtime_loader.load_approved_model` is the ONLY path from a trained
artifact to the runtime `packages.prediction.registry.model_registry`. It looks up the
evidence for the exact `(strategy_name, strategy_version)` pair and raises
`ModelNotApprovedError` unless that evidence's status is `APPROVED` — proven by
`test_load_approved_model_refuses_when_no_evidence` and
`test_load_approved_model_refuses_when_evidence_not_approved`. There is no fallback that
substitutes a heuristic agent confidence constant for a missing approved probability
model (implementation plan section 19's explicit prohibition).

## 6. Artifact audit trail

Every published `StrategyEvidence` is registered into the runtime
`packages.recommendation.evidence_service.evidence_registry` (the same registry the chat
`get_strategy_evidence` tool and `RecommendationService` already read) AND persisted as a
JSON file under `artifacts/evidence/{evidence_id}.json` for offline audit, independent of
the runtime process's in-memory state.
