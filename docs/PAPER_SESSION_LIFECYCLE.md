# Paper Session Lifecycle Specification

## 1. Session Status Lifecycle State Machine

```
   CREATED
      │
      ▼
  VALIDATING ──(Error)──► FAILED
      │
      ▼
  WARMING_UP ──(Error)──► FAILED
      │
      ▼
    READY ─────► STOPPED
      │
      ▼
   RUNNING ◄──► PAUSED
   │  ▲
   │  │
   ▼  │
  DEGRADED ──► HALTED ──► RECOVERY_REQUIRED ──► READY
   │             │
   ▼             ▼
 STOPPING      FAILED
   │
   ▼
STOPPED
```

---

## 2. Transition Rules Matrix

| From Status | Allowed To Statuses | Trigger / Conditions |
|---|---|---|
| `CREATED` | `VALIDATING` | API validation call or session start initiation |
| `VALIDATING` | `WARMING_UP`, `FAILED` | Config snapshot validation complete |
| `WARMING_UP` | `READY`, `DEGRADED`, `FAILED` | Baseline rolling windows and feature calculators warmed up |
| `READY` | `RUNNING`, `STOPPED` | Market stream connected & user start command |
| `RUNNING` | `PAUSED`, `DEGRADED`, `HALTED`, `STOPPING`, `FAILED` | Stream incident, risk breach, or user control action |
| `PAUSED` | `RUNNING`, `STOPPING`, `HALTED` | User resume command or halt on system event |
| `DEGRADED` | `RUNNING`, `HALTED`, `FAILED` | Clock skew > 5s or stream drop |
| `HALTED` | `RECOVERY_REQUIRED` | Recovery process initiated |
| `RECOVERY_REQUIRED` | `READY`, `FAILED` | Journal replay & state reconciliation complete |
| `STOPPING` | `STOPPED` | Open paper orders cancelled & session state saved |
| `STOPPED` | None (Terminal) | Session terminated cleanly |
| `FAILED` | None (Terminal) | Fatal error or unrecoverable invariant breach |

---

## 3. Direct Jump Prohibition
Direct state jumps (e.g. `CREATED` → `RUNNING` or `HALTED` → `RUNNING`) are strictly forbidden by `PaperSessionManager` and will raise `INVALID_STATUS_TRANSITION`.
