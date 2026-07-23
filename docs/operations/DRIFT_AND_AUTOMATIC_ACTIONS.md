# Drift Detection and Conservative Automatic Actions (Phase 11)

`packages/monitoring/{drift,evidence_lifecycle}.py`.

## Drift assessment

`BaselineDriftService.assess(subject, metric_name, baseline, current)` - a documented,
versioned (`DRIFT_POLICY_VERSION = "drift_v1"`) relative-deviation threshold, not a statistical
test tuned to any backtest result.

```
deviation = |current - baseline| / |baseline|      (or |current| if baseline == 0)

deviation >= 0.50  -> SEVERE    -> DISABLE_AND_REQUIRE_MANUAL_REVIEW
deviation >= 0.25  -> MODERATE  -> MARK_DEGRADED
deviation >= 0.10  -> LOW       -> MONITOR
deviation <  0.10  -> NONE      -> (no action)
```

Missing `baseline` or `current` is never silently treated as "no drift" - it returns
`severity=NONE` but with `reason_codes=["INSUFFICIENT_DATA_FOR_DRIFT_ASSESSMENT"]` and
`recommended_action="COLLECT_MORE_BASELINE_DATA"`, an explicit, distinguishable case.

## Automatic evidence lifecycle actions

`apply_drift_action(store, key, drift, audit_log)` applies the conservative transition a drift
assessment implies to the exact-match evidence record for `key`:

- `SEVERE` on an `APPROVED` or `DEGRADED` record -> `DISABLED`.
- `MODERATE` on an `APPROVED` record -> `DEGRADED`.
- Anything else (including `SEVERE`/`MODERATE` on `RESEARCH_ONLY`/`INSUFFICIENT`/`REJECTED`/
  `STALE`/`DISABLED` records) -> no action. There is nothing more conservative to move a
  `REJECTED`/`DISABLED` record to, and a `RESEARCH_ONLY` record was never trading capital in
  the first place.

**There is no function anywhere in this module that can move a record back toward
`APPROVED`.** Re-promotion is Phase 12's retraining workflow's job, and even that never
auto-promotes (a retrained model always enters `RESEARCH_ONLY` - see
`docs/operations/RETRAINING_WORKFLOW.md`). Every automatic action is recorded to the evidence
audit log (`evidence_auto_degraded` / `evidence_auto_disabled`) with the triggering drift
metric and severity.

## Kill switch

`KillSwitch` can only be **tripped** automatically (`.trip(reason_code)`) - resetting requires
an explicit named human actor (`.reset(actor)` raises `ValueError` without one) and is always
audit-logged (`kill_switch_tripped` / `kill_switch_reset`). This mirrors the same
human-actor-required pattern as `packages.retraining.workflow.rollback_model_version`.

`should_disable_new_proposals(kill_switch)` is the read-side a caller (a future orchestration
layer) would consult before generating new proposals while the switch is active - this
campaign wires the switch itself and its trip/reset semantics; wiring it into
`packages.runtime.recommendation_service`'s decision path is a natural next step that doesn't
require changing this module.

## Manual review requirement

`SEVERE` drift's recommended action is explicitly `DISABLE_AND_REQUIRE_MANUAL_REVIEW`, not
just `DISABLE` - the reason code is preserved in the registry/evidence transition's own
`reason_codes` field so a human reviewer has the full context without re-deriving it.
