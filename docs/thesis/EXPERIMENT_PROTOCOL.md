# Experiment Protocol

Status: **ANALYSIS PROTOCOL V1 LOCKED — COLLECTION ADAPTER PENDING**

The normative configuration is `configs/research/thesis_protocol_v1.json`. Its canonical
SHA-256 is pinned in code and tests. The validator rejects every altered copy using the same
schema version; any change requires a new version and digest. This locks the planned analysis,
but collection cannot start until the research-only ablation adapter named in the configuration
is implemented and reviewed.

## Protocol identity

Protocol v1 fixes:

- BTCUSDT at 4h, evaluated every four hours in UTC;
- collection from 2026-08-01 00:00 inclusive to 2027-08-01 00:00 exclusive;
- one 4h outcome horizon and six contiguous two-month temporal folds;
- 4h purge and 4h embargo;
- exact component versions, variants, paired contrasts, endpoint, missing-data policy,
  inferential method, multiplicity correction, seed, completeness gate, and stopping rule.

The protocol checksum and source commit are captured before the first clock. The confirmatory
experiment ID is derived from that checksum, analysis identity, market scope, as-of time,
input/evidence checksums, and model/prompt versions. Existing IDs are never overwritten.

## Required variants

| Variant ID | Definition | Production authority |
|---|---|---|
| `quantitative_only` | Approved quantitative prediction; no specialists or debate | No action |
| `single_agent` | Technical specialist v1 only; no debate or derivatives | No action |
| `multi_no_debate` | Technical, derivatives, quantitative specialists v1; equal static weights | No action |
| `multi_with_debate` | `multi_no_debate` plus one bull/bear round v1 | No action |
| `without_verification` | Full debated static configuration with Verification omitted | No action |
| `with_verification` | `without_verification` plus research verification mask | No action |
| `without_derivatives` | Technical and quantitative agents; derivative fields withheld | No action |
| `with_derivatives` | `without_derivatives` plus the derivative agent and four fixed fields | No action |
| `static_weights` | Full debated configuration with fixed equal weights | No action |
| `dynamic_weights_research_only` | `static_weights` with only the frozen trailing-score rule changed | No action |

Omitting Verification is an analytical ablation only. It cannot authorize paper or live action.
All real components are bound to full Python import paths. The risk component is
`packages.agents.verification_risk.AnalysisRiskEngine`, not an invented substitute. The model
rule selects the latest
exact BTCUSDT/4h artifact whose registry entry and approval receipt predate collection; a
deterministic ID/version tie-break is frozen. No match yields `NO_APPROVED_MODEL`.

Production `ManagerAgent`, `AnalysisRiskEngine`, and `VerificationAgent` are incompatible with
some reduced arms and therefore never determine the primary ablation endpoint. Every arm uses
the same no-action `ResearchAblationDecisionFunction`: configured component scores enter one
weighted base score, the debate layer is applied only when enabled, and the research evidence
verification mask is applied only when enabled. Production component outputs remain captured
observational artifacts. The no-Verification arm never instantiates production Manager/Risk.
A future collection adapter must supply checksum-bound inputs to this common function. Until
it passes independent review, `collection_may_start=false`.

## Paired primary contrasts

| Contrast | Control | Treatment | Sole changed component |
|---|---|---|---|
| `C1_AGENT_INCREMENT` | `quantitative_only` | `single_agent` | Technical specialist |
| `C2_DEBATE_INCREMENT` | `multi_no_debate` | `multi_with_debate` | Bull/bear debate |
| `C3_VERIFICATION_INCREMENT` | `without_verification` | `with_verification` | Verification |
| `C4_DERIVATIVES_INCREMENT` | `without_derivatives` | `with_derivatives` | Derivatives agent and its fixed evidence fields |
| `C5_DYNAMIC_WEIGHT_INCREMENT` | `static_weights` | `dynamic_weights_research_only` | Weighting rule |

The machine protocol declares the exact differing fields for each pair. Contract tests prove
that all other fields are equal and exercise debate, verification-mask and weighting changes
through the same function. The derivatives agent, its fixed evidence fields and required
renormalization are one declared composite intervention; the single-agent arm adds only the
technical component to the shared quantitative base.

The exact static decimals, derivatives fields, prompt/component versions, and dynamic rule are
in the normative JSON. The dynamic rule reads one conflict-free agent assessment per paired
analysis from the `static_weights` arm over `[as_of-180 calendar days, as_of)`. BULLISH/BEARISH
scores `+1` when its direction matches the matured public 4h return, `-1` when opposite, and
`0` for flat/NEUTRAL/unavailable/rejected. Only outcomes available strictly before the current
as-of time enter. Each agent requires 30 matured observations; records are ordered by source
as-of then paired ID, conflicts make the proposal unavailable, and exact-boundary outcomes
are excluded. The rule clamps `1 + Decimal mean(agent_score)` to `[0.25, 1.75]`, then
normalizes. This predeclared research-only online adaptation may use prior matured
collection-window outcomes, but may not update a model, prompt, or threshold. Insufficient
history is `UNAVAILABLE`; it never falls back to static weights.

## Collection procedure

1. Freeze the protocol, configurations, versions, and checksums.
2. Create variant records from one shared eligible point-in-time snapshot.
3. Persist the complete experiment envelope before the outcome horizon matures.
4. Append one outcome event after maturity; never rewrite the envelope.
5. Export the full attempted cohort, including unavailable and rejected records.
6. Verify checksums and manifest counts before analysis.
7. Run the predeclared analysis without loosening gates or filtering unfavorable results.

## Primary endpoint and hypotheses

Prices come from Binance public BTCUSDT spot klines through the repository's public adapter.
The reference is the final Decimal close of `[as_of_time-4h, as_of_time)` and the outcome is
the final Decimal close of `[as_of_time, as_of_time+4h)`. Return is
`(outcome_close-reference_close)/reference_close` with no float conversion. Its sign uses
exact zero tolerance.

For each scheduled clock, BUY scores `+1` on a positive return, `-1` on a negative return, and
`0` on an exactly flat return. HOLD, `NO_DECISION`, `UNAVAILABLE`, rejection, and a variant
runtime failure score `0`; SELL/SHORT is invalid in this campaign. Quantitative and specialist
BULLISH/NEUTRAL/BEARISH map to `+1/0/-1` inside the common research-only function. A positive
final score maps to BUY and a non-positive score to HOLD. An enabled failed verification mask
maps to REJECTED. Production Manager recommendations do not change the primary endpoint. Each
primary estimand is the arithmetic mean paired treatment-minus-control score over all
public-outcome clocks.

## Sample size and stopping

No observed sample size is claimed. The information target is a census of every scheduled 4h
clock in the fixed one-year window. There is no efficacy stopping. The only early stop is a
documented safety/legal hard blocker. Analysis requires at least 90% of scheduled clocks to
have public outcomes and all ten attempted variant records; the realized count remains
`PENDING_EVIDENCE`.

## Statistical analysis

The frozen primary analysis uses 42-clock blocks and seed `15042026`. Its circular bootstrap
samples start indexes uniformly with replacement, takes 42 clocks with wraparound,
concatenates blocks, truncates to the original length, and reports the 2.5/97.5 percentiles
over 10,000 resamples. The randomization test partitions clocks into non-overlapping 42-clock
blocks anchored at collection start, retains a short final block, flips each block-sum sign,
and compares the absolute mean using `(1 + exceedances)/(10000 + 1)`. Holm step-down correction
controls the five primary contrasts at alpha 0.05.

Variant-caused missing/no-decision/error states score zero in the all-attempt endpoint. A
missing public market outcome stays as a null in its original 42-clock calendar block and is
excluded from the main mean denominator for every variant; time is never compressed. Block
sums ignore null slots. Bootstrap replicates retain nulls and use their sampled non-null
denominator, redrawing only an all-null replicate. The worst-case sensitivity assigns
treatment `-1` and control `+1` for every missing public clock.

All secondary endpoints are exploratory-only. The normative JSON freezes their formulas,
denominators, units, paper-only fee/slippage/equity source, currency grouping, and null rules.
They cannot support a confirmatory claim. No interval, p-value, or significance result exists
until real evidence is collected.

## Failure and exclusion log

Every attempted record must end in an observed status such as `COMPLETE`, `UNAVAILABLE`,
`NO_APPROVED_MODEL`, `NO_DECISION`, or an explicit rejection/error code. Exclusions require a
protocol-defined reason and remain visible in the export.

## Acceptance gate for an analyzable cohort

- Protocol and configuration checksums predate outcomes.
- Input and evidence lineage passes anti-lookahead validation.
- Variant input parity is verified.
- Required outcomes are time-matured and checksummed.
- All attempted records and failure statuses are exported.
- No gate or prompt was changed after outcome inspection.
- Paper metrics are labeled simulated.
- Statistical review is complete.

Until every item passes, comparative results remain `PENDING_EVIDENCE`.
