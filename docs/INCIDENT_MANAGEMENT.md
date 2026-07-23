# Incident Lifecycle Management

## Valid State Transitions
Incident status transitions follow a strict finite state machine:
```
OPEN ---> ACKNOWLEDGED ---> INVESTIGATING ---> MITIGATED ---> RESOLVED ---> CLOSED
```

## Audit Trail
Every transition logs the actor, timestamp, status change, and optional resolution note. Closed incidents cannot be re-opened; a new incident with a fresh fingerprint must be reported if issues recur.
