# Security Threat Model

## Asset Inventory
1. Source Code & Git History
2. Risk Policies & Execution Controls
3. Paper Trading Accounts & Ledger
4. Historical Backtest Datasets
5. Database & Redis Credentials
6. Software Bill of Materials & Release Candidates

## Threat Actors
- Unauthenticated Internet Scanner
- Low-Privilege Authenticated User
- Compromised Operator Account
- Malicious Market Data Feed Payload

## Mitigation Matrix
- **Credential Theft**: Hardened environment secrets manager, zero hard-coded secrets.
- **Unauthorized Action**: Role-Based Access Control (RBAC) with default deny.
- **Malicious Market Feed**: Data Guardian validation, sequence gap checks, OHLC bounds.
- **Live Trading Leakage**: Hardcoded fail-closed startup assertions.
