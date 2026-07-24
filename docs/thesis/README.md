# Research and Thesis Package

Status: **STRUCTURE COMPLETE — RESULTS PENDING EVIDENCE**

This package is a thesis-ready protocol, not a completed empirical thesis. The repository
contains real historical backtest artifacts, but it does not yet contain a complete,
time-matured experimental cohort for the end-to-end quantitative and multi-agent ablations
defined here. Every comparative result therefore remains `PENDING_EVIDENCE`.

## Problem statement

The project investigates whether an evidence-grounded, temporally correct multi-agent
decision workflow can improve the quality and auditability of a crypto market advisory
system compared with simpler quantitative or single-agent baselines, while preserving
fail-closed behavior when required inputs are unavailable.

The system is an advisor operating only in `RESEARCH`, `SHADOW`, and `PAPER` modes. It is not
a live execution system.

## Research questions

1. Does the multi-agent workflow change decision quality relative to quantitative-only and
   single-agent baselines on the same point-in-time inputs?
2. What incremental effect do debate, verification, derivatives evidence, and research-only
   dynamic weighting have?
3. How do unavailable, stale, or contradictory inputs affect abstention, rejection, and
   reproducibility?
4. Are any observed differences stable across predeclared temporal folds and market regimes?
5. What operational costs, latency, and failure modes accompany each architecture variant?

These are research questions, not claims. No answer is asserted until the corresponding
cohort passes the protocol in [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md).

## Related architecture

The evaluated path is:

```text
public point-in-time market data
  -> feature and evidence lineage
  -> quantitative model
  -> specialist agents
  -> bull/bear debate
  -> verification and risk gates
  -> manager recommendation
  -> shadow/paper outcome capture
  -> append-only experiment export
```

The implementation and authority boundaries are described in
`docs/campaign/CRYPTO_MULTI_AGENT_SYSTEM_PLAN.md`. Source observations have observation,
availability, and receipt clocks. Model artifacts require registry approval. Agent outputs
cannot bypass verification, risk, or manager authority. Paper fills are simulations and are
never represented as live orders.

An externally sourced literature review and formal bibliography have not been completed and
are deliberately not invented here. Citation review remains future academic work.

## Methodology

The methodology is defined in [METHODOLOGY.md](METHODOLOGY.md). It predeclares temporal
splits, cohort identity, input parity, exclusion rules, metrics, and the separation between
exploratory analysis and confirmatory claims.

## Dataset

Eligible inputs are immutable experiment envelopes and matured outcome events conforming to
`experiment_record_v1` and `experiment_outcome_v1`. The canonical fields are documented in
`docs/experiments/DATA_DICTIONARY.md`; the thesis-specific cohort fields are documented in
[DATA_DICTIONARY.md](DATA_DICTIONARY.md).

The current repository includes a real historical alpha-research ledger for BTC/USDT and
ETH/USDT. Its own evidence report states that no configuration cleared its cross-symbol
promotion gate. That ledger is prior engineering evidence and must not be silently combined
with the not-yet-collected end-to-end ablation cohort.

## Baselines

- Quantitative-only.
- Single-Agent.
- Multi-Agent without debate.
- Static agent weights.

Each baseline must receive the same eligible market scope, as-of time, outcome horizon, and
data-availability policy as its paired treatment.

## Experiments and ablations

The predeclared comparison matrix is in [RESULTS_STATUS.md](RESULTS_STATUS.md). It includes:

- Quantitative-only.
- Single-Agent.
- Multi-Agent without debate.
- Multi-Agent with debate.
- Without Verification.
- With Verification.
- Without derivatives.
- With derivatives.
- Static weights.
- Dynamic weights, research-only.

No variant may alter production prompts, model approval, or trading configuration during an
experiment. Dynamic weights are proposals only.

## Results

All end-to-end comparative results are `PENDING_EVIDENCE`. No metric value, sample size,
effect direction, confidence interval, p-value, or statistical significance is claimed.

## Error analysis

`PENDING_EVIDENCE`. Once a valid cohort exists, errors will be grouped by explicit reason
codes, missing/stale inputs, regime, disagreement, verification outcome, and horizon. Null
outcomes will remain null and will not be counted as failures or zero returns.

## Limitations

- The primary MVP scope is BTCUSDT at 4h; generalization is not established.
- Crypto market structure is non-stationary and vulnerable to selection bias.
- Provider availability, licensing, and model behavior can change.
- Shadow and paper outcomes do not demonstrate executable live performance.
- The advanced-source and ETH paths are disabled unless separately configured and audited.
- No real end-to-end ablation cohort currently supports comparative conclusions.

## Ethics and safety

- Live trading and private exchange APIs remain disabled.
- Only public or explicitly licensed research data is eligible.
- No secret, private credential, fabricated evidence, or fabricated confidence is permitted.
- Missing inputs lead to unavailable or rejected states, never silent fallback.
- Research outcomes must not be presented as financial advice or live trading results.
- Model and dynamic-weight promotion remain separate human-governed actions.

## Reproducibility

The required environment, source revision, data checksums, configuration, seeds, commands,
exports, and audit outputs are specified in [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Future work

1. Pre-register and collect a complete time-matured end-to-end cohort.
2. Complete license review for any advanced external source.
3. Run the ablation matrix without changing gates after outcomes are observed.
4. Perform blinded error analysis and statistical review.
5. Add verified academic citations and a literature synthesis.
6. Reassess external validity across assets and timeframes without BTC-model fallback.
