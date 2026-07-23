# Authentication & Role-Based Access Control (RBAC)

## Standard Roles
1. `VIEWER`: Read-only access to dashboard widgets.
2. `ANALYST`: Backtest creation and evaluation.
3. `OPERATOR`: Paper trading session lifecycle management.
4. `RISK_OPERATOR`: Risk Governor and Hard Stop management.
5. `SECURITY_AUDITOR`: Read audit logs, incident management, and security reports.
6. `ADMINISTRATOR`: Full administrative configuration management.

## Default Deny Policy
Unauthenticated or unauthorized principal requests fail immediately with `403 Forbidden` / `401 Unauthorized`.
