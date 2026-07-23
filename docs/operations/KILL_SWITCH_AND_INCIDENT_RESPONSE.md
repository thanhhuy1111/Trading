# Kill Switch and Incident Response (this campaign's additions)

This document covers the kill-switch and incident-relevant additions from Phases 6-11. It
complements the pre-existing `docs/KILL_SWITCH_POLICY.md` and
`docs/SECURITY_INCIDENT_RESPONSE.md` rather than replacing them - those documents cover the
production paper-trading kill switch and general incident process; this one covers what's new
in the architecture-completion campaign.

## Two independent kill-switch surfaces

1. **`PortfolioSnapshot.kill_switch_active`** (`packages/ports/interfaces.py`) - read by
   `BaselinePortfolioRiskGovernor.evaluate()`. When `True`, every candidate is `HALT`ed
   regardless of every other check - checked second, right after missing-state, before even
   drawdown/loss limits. A caller supplies this flag from whatever system owns the real
   portfolio kill-switch state (out of scope for this task to wire to a specific source).

2. **`packages.monitoring.evidence_lifecycle.KillSwitch`** - a new, independent, in-process
   switch tied to monitoring/drift signals. Can only be **tripped** automatically
   (`.trip(reason_code)`, e.g. from a `SEVERE` drift assessment); **reset requires a named
   human actor** (`.reset(actor)` raises `ValueError` without one) and both trip and reset are
   audit-logged. `should_disable_new_proposals(switch)` is the read-side check.

These are deliberately not the same object - a portfolio-level circuit breaker and a
monitoring-driven research circuit breaker have different owners and different recovery
processes, and conflating them would make an automatic monitoring action able to halt real
capital decisions (or vice versa) without a clear audit trail of which system asked for it.

## Automatic vs. human-gated actions - the conservative-only direction

| Trigger | Automatic action | Requires human to reverse? |
|---|---|---|
| `SEVERE` drift on approved evidence | Evidence `APPROVED`/`DEGRADED` -> `DISABLED` | Yes - no automatic re-promotion exists |
| `MODERATE` drift on approved evidence | Evidence `APPROVED` -> `DEGRADED` | Yes |
| Repeated drift/system-degraded signals | `KillSwitch.trip()` (an operator/future orchestration decision, not built into this campaign's runtime) | Yes - `.reset(actor)` |
| A retrained model finishing training | Registered `RESEARCH_ONLY`, evidence `INSUFFICIENT` | Yes - promotion is always a separate human action |
| Portfolio-level kill switch active | Every candidate `HALT`ed | Yes - owned by whatever system sets `PortfolioSnapshot.kill_switch_active` |

Every row moves toward more caution automatically and requires a human to move back. No
function anywhere in `packages.monitoring` or `packages.retraining` can automatically approve,
promote, or re-enable anything.

## Testing

`tests/unit/test_monitoring.py::test_kill_switch_can_only_be_reset_by_a_named_actor` and the
kill-switch-active scenario in `tests/acceptance/test_final_acceptance.py` cover both switches.
