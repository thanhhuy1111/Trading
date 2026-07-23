# Order State Machine Specification

## 1. Valid Transitions
- `PENDING_EXECUTION` -> `VALIDATING`
- `VALIDATING` -> `READY` | `BLOCKED` | `EXPIRED` | `REJECTED`
- `READY` -> `SUBMISSION_PENDING`
- `SUBMISSION_PENDING` -> `SUBMITTED` | `REJECTED` | `FAILED_RETRYABLE` | `UNKNOWN`
- `SUBMITTED` -> `ACKNOWLEDGED` | `PARTIALLY_FILLED` | `FILLED` | `CANCEL_PENDING` | `EXPIRED` | `UNKNOWN`
- `ACKNOWLEDGED` -> `PARTIALLY_FILLED` | `FILLED` | `CANCEL_PENDING` | `EXPIRED`
- `PARTIALLY_FILLED` -> `PARTIALLY_FILLED` | `FILLED` | `CANCEL_PENDING` | `CANCELLED` | `EXPIRED`
- `CANCEL_PENDING` -> `CANCELLED` | `FILLED` | `PARTIALLY_FILLED` | `UNKNOWN`
- `FAILED_RETRYABLE` -> `SUBMISSION_PENDING` | `FAILED_FINAL`

## 2. Transition Rules
- Every transition must be logged to `order_state_transitions` with timestamp, trigger, and reason codes.
- Arbitrary status jumps (e.g. `PENDING_EXECUTION` -> `FILLED`) are strictly prohibited and raise validation errors.
