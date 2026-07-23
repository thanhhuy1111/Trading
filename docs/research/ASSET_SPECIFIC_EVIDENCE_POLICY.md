# Asset/Timeframe/Model Evidence Policy

## Purpose

An evidence record answers exactly one question: *"has this exact strategy configuration,
running this exact model, on this exact symbol and timeframe, cleared the promotion gate?"*
It must never be asked to answer a nearby question ("what about a similar symbol", "what about
a similar timeframe", "what about a slightly different model version") — those are different
questions with no guaranteed relationship to the answer for the one actually being asked. This
policy makes that binding explicit and enforces it at the lookup layer
(`packages/evidence/store.py`).

## Statuses

| Status | Meaning |
|---|---|
| `UNIVERSAL_APPROVED` | Cleared the promotion gate independently on **every** symbol the campaign tested it against. |
| `ASSET_SPECIFIC_APPROVED` | Cleared the promotion gate on this exact symbol/timeframe. Says nothing about any other symbol/timeframe. |
| `RESEARCH_ONLY` | Net-positive in aggregate out-of-sample but fails a gate criterion (e.g. Sharpe, fold-profitability ratio). Never usable as trading evidence — research signal only. |
| `INSUFFICIENT` | Fewer than the gate's minimum out-of-sample trade count. Not enough evidence to judge either way. |
| `REJECTED` | Clearly failed the gate (negative expectancy, negative aggregate PnL, etc.). |
| `STALE` | Was `*_APPROVED` but has aged past the freshness window (30 days by default — see `DEFAULT_EVIDENCE_TTL`) or the underlying dataset/gate/code changed. Computed dynamically at lookup time, not a status that gets silently left stale in storage. |

Only `UNIVERSAL_APPROVED` and a fresh `ASSET_SPECIFIC_APPROVED` are "actionable"
(`EvidenceStore.is_actionable`). Every other status — including a missing record — must block
a trade proposal identically to `REJECTED`.

## The exact-match binding key

`packages/evidence/models.py: EvidenceKey` — a plain `NamedTuple` (tuple equality, no
normalization, no `__eq__` override that could introduce fuzzy matching) over:

```
strategy_name, strategy_version, symbol, timeframe,
model_type, model_version, feature_version, label_version,
dataset_checksum, gate_version, config_hash, code_commit
```

Every field must match exactly for `EvidenceStore.lookup()` to return a record. In particular,
this is what each field is protecting against:

| Field | Protects against |
|---|---|
| `symbol` | BTC/USDT evidence being reused for ETH/USDT (this checkpoint's own failure analysis shows this is not a safe assumption — see `BTC_ETH_FAILURE_ANALYSIS.md`) |
| `timeframe` | 1h evidence being reused for 4h, or 1d for either |
| `config_hash` | Two configs sharing a `strategy_name` (e.g. a future tuning pass) silently inheriting each other's evidence |
| `model_type` / `model_version` | A rule-based result being read as if it were an ML-model result, or one ML model version's calibration being applied to another's outputs |
| `feature_version` / `label_version` | A result computed under one feature or labeling scheme being trusted after either changes |
| `dataset_checksum` | Evidence surviving a change to the underlying historical data without being invalidated |
| `gate_version` | Evidence approved under a looser historical gate being trusted after the gate tightens (`packages/research/gate.py: GATE_VERSION`) |
| `code_commit` | Evidence surviving a change to the engine/agent code that produced it |

**Forbidden fallbacks** (explicitly tested in `tests/unit/test_evidence_exact_match.py`):
BTC → ETH, 1h → 4h, SOL → BNB, one `model_version` → another. A lookup miss returns `None`
(or, if the caller treats a miss and `REJECTED` the same way — which every caller must —
identical to `REJECTED`). It never returns "the closest thing we have."

## Walk-forward dataset checksum

The campaign backtests each out-of-sample fold on its own sliced dataset (see
`packages/research/campaign.py`), so a single (symbol, config) evidence record spans 3 dataset
checksums, not 1. `compute_evidence_dataset_checksum` combines the sorted per-fold checksums
into one deterministic value: same 3 folds → same combined checksum; any change to any fold's
data → a different one, correctly invalidating the record.

## Checkpoint 1 field values

Since no ML model has been trained yet (Phase 7 is a later checkpoint):

- `model_type = "RULE_BASED_MULTI_AGENT"`
- `model_version = "n/a"` (explicit placeholder — there is no model to version yet, and this
  is never treated as a wildcard; it still participates in exact matching like any other field)
- `feature_version = "standard_v1"` (the feature set name used by `FeaturePipeline.compute`)
- `label_version = "meta_label_v1"` (the `net_return_bps > 0 => ACCEPT` rule already computed
  per-candidate — see `packages/candidates/models.py: TradeCandidate.meta_label`)
- `gate_version = "gate_v1"` (`packages/research/gate.py`)

## Result of applying this policy to the current campaign

`packages/evidence/builder.py` converted the 30 (symbol, config) gate results into evidence
records (`docs/research/experiments/EVIDENCE_RECORDS.csv`):

| Status | Count |
|---|---|
| `UNIVERSAL_APPROVED` | 0 |
| `ASSET_SPECIFIC_APPROVED` | 14 (all BTC/USDT) |
| `RESEARCH_ONLY` | 1 |
| `INSUFFICIENT` | 0 |
| `REJECTED` | 15 (all ETH/USDT except the one RESEARCH_ONLY case) |

Zero `UNIVERSAL_APPROVED` records exist. If a future runtime recommendation flow queries
evidence for ETH/USDT under any of these 15 configurations, the exact-match lookup correctly
returns nothing actionable — it will not substitute the BTC/USDT record for the same
`strategy_name`, even though BTC/USDT passed.
