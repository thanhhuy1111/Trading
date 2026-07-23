# Security Architecture

## Overview
The Security Architecture establishes defensive security boundaries, role-based access control (RBAC), software supply chain provenance (SBOM), container hardening, and fail-closed safety boundaries across the crypto multi-agent trading platform.

```
+-------------------------------------------------------------------------+
|                  React Security & Operations Console                    |
|   - Security Gate  - Control Matrix  - Risk Register  - SBOM & Drills   |
+-------------------------------------------------------------------------+
                                    ^
                                    | REST API (/security/*)
+-------------------------------------------------------------------------+
|                       FastAPI Hardened Server                           |
|   - RBAC Manager  - Input Validator  - Output Sanitizer  - DR Service   |
+-------------------------------------------------------------------------+
            ^                       ^                       ^
            |                       |                       |
+----------------------+  +--------------------+  +--------------------+
|  RBAC Manager        |  | SBOM Generator     |  | Fail-Closed Boundary|
|  (6 Roles / Deny)    |  | (CycloneDX 1.4)    |  | (LIVE_TRADING=OFF)  |
+----------------------+  +--------------------+  +--------------------+
```

## Security Invariants
- `LIVE_TRADING_ENABLED=false` and `PRIVATE_EXCHANGE_API_ENABLED=false` remain strictly enforced.
- Execution engine supports ONLY `PAPER_TRADING` and `HISTORICAL_SIMULATION`.
- RBAC enforces default deny across all administrative endpoints.
