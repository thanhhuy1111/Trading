# Security Operational Runbook

## Live Trading Flag Attempt Detected
- **Symptom**: Startup failure `SECURITY_KILL_SWITCH: LIVE_TRADING_ENABLED is True!`.
- **Action**: Immediately inspect environment config `.env`; enforce `LIVE_TRADING_ENABLED=false`; log CRITICAL security incident.

## Credential Exposure Suspicion
- **Symptom**: Sensitive key flagged in external log export.
- **Action**: Revoke affected credential immediately; run `SensitiveDataRedactor` validation; deploy updated configuration snapshot.
