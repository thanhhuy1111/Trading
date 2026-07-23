# Disaster Recovery Plan

## Recovery Protocol
1. Restore clean PostgreSQL database instance from encrypted backup.
2. Run database migration `012_security_hardening.py`.
3. Execute `position_reconciliation_service.reconcile_portfolio()` verifying 16 accounting checks.
4. Verify paper session status enters `RECOVERY_REQUIRED` mode prior to resumption.
