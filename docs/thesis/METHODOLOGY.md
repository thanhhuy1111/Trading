# Methodology

Status: **PROTOCOL DEFINED — EMPIRICAL RESULTS PENDING EVIDENCE**

## Study design

The study is a point-in-time, paired, longitudinal comparison of advisory variants. One
analysis identity and one eligible input snapshot are evaluated across predeclared variants.
Treatments may remove a component, but they may not gain later data, a different outcome
horizon, or a more permissive approval gate.

Exploratory runs may help debug the protocol but cannot become confirmatory evidence.
Confirmatory cohort IDs and configuration checksums must be fixed before their outcomes
mature.

The normative machine-readable analysis specification is
`configs/research/thesis_protocol_v1.json`. Protocol v1 fixes BTCUSDT, the 4h timeframe, a UTC
decision at every closed 4h candle from 2026-08-01 00:00 inclusive through 2027-08-01 00:00
exclusive, and one 4h outcome horizon. This is a census of scheduled clocks in a fixed calendar
window, not a claim about an observed sample size. Collection remains blocked until the
research ablation adapter is implemented and independently reviewed.

## Unit of analysis

The unit is one immutable `(analysis_id, symbol, timeframe, as_of_time, horizon, variant)`
record linked to:

- exact raw and normalized input checksums;
- feature and evidence snapshots;
- model and prompt versions;
- agent, debate, verification, risk, and manager outputs when applicable;
- data-quality and provider telemetry;
- one separately appended, time-matured outcome event.

Repeated horizons are distinct cohorts. They are never pooled into one denominator.

## Temporal correctness

- The exact collection folds are six contiguous two-month UTC strata (`F1` through `F6`) in
  the normative protocol.
- Training, tuning, and evaluation windows are ordered and non-overlapping.
- Every input must have `available_at <= as_of_time` and `received_at <= as_of_time`.
- Purge and embargo are both fixed at 4 hours; no collection-window outcome may be used to fit
  or tune any component.
- Outcomes are appended only after the declared horizon has matured.
- A 4h outcome matures no earlier than `as_of_time + 4h` and uses the next closed 4h candle
  close. Late or revised observations retain their original availability lineage and are
  excluded if first received after the paired as-of time.
- Future evidence, stale inputs, and corrupted artifacts are rejected and recorded.
- All ten variants must match on symbol, timeframe, as-of time, raw-input checksum, and
  evidence-snapshot checksum before pairing.

## Cohort eligibility

An analysis is eligible only if it has a canonical experiment envelope, declared variant,
known configuration checksum, complete required lineage, and an outcome event that matured
under the same horizon definition. Exclusion must use a predeclared reason code.

Unavailable inputs remain part of operational reporting. They are not silently dropped from
availability, abstention, or rejection denominators.

## Comparison controls

Paired variants use the same:

- market observation and availability cutoff;
- symbol, timeframe, horizon, and fee/slippage assumptions;
- approved quantitative artifact when the variant includes one;
- provider/model versions, except where the component itself is the intervention;
- outcome definition and evaluation clock.

The protocol forbids changing approval thresholds, risk limits, or prompts after seeing
comparative outcomes.

## Outcome families

Planned outcome families are:

1. Decision quality: correctness and abstention/rejection rates where labels are defined.
2. Simulated economic outcomes: paper return, PnL, drawdown, win rate, and fee/slippage
   impact, always labeled simulated.
3. Reliability: unavailable, stale, schema-invalid, provider-error, and retry rates.
4. Evidence quality: missing-evidence and future-evidence rejection rates.
5. Operational cost: observed latency, tokens, and provider cost when available.

The primary all-attempt endpoint gives `+1` to a correct BUY direction, `-1` to an
incorrect BUY direction, and `0` to a flat return or any HOLD, `NO_DECISION`, `UNAVAILABLE`,
rejection, or variant runtime failure. Its population is every scheduled clock with a matured
public close outcome; the estimand is the mean paired treatment-minus-control score. This
intent-to-treat definition prevents variant-caused abstention from disappearing through
complete-case filtering. Null market outcomes stay null and remove the same clock from every
variant.

## Analysis policy

- Report observation counts for every metric and variant.
- Report the all-attempt paired primary difference over every common market-outcome clock.
- Report decision-conditional accuracy and economic outcomes only as secondary endpoints.
- Preserve rejected and unavailable cases as explicit outcomes.
- Use temporal-fold summaries rather than random row shuffling.
- Treat regime and asset breakdowns as predeclared strata or label them exploratory.
- Record all attempted variants, including failed runs.

Protocol v1 freezes circular 42-clock block-bootstrap construction, non-overlapping 42-clock
sign-flip blocks anchored at collection start, final-remainder handling, the arithmetic-mean
test statistic, 10,000 resamples with seed `15042026`, and Holm correction across five primary
contrasts at alpha 0.05. It also defines worst-case missing public outcomes as treatment `-1`
and control `+1`. These are planned methods, not observed intervals, p-values, or significance
claims.

Missing public outcomes remain null slots inside the original calendar-anchored block.
Neither bootstrap nor sign-flip input is compressed across a gap. The main denominator is the
number of non-null public-outcome slots; a deterministic gapped-series contract test protects
this rule.

There is no efficacy stopping. Collection ends only at the fixed calendar boundary or a
documented safety/legal hard blocker. The cohort is not declared analyzable unless at least
90% of scheduled clocks have a public outcome and all ten attempted variant records. Realized
counts and every empirical result remain `PENDING_EVIDENCE`.

## Safety interpretation

Research and paper observations cannot establish live executability. A favorable research
result cannot promote a model, enable a source, change production agent weights, or enable
live trading. Those actions remain outside this campaign and behind independent gates.
