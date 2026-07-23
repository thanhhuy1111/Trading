# Paper Trading Safety Invariants & Non-Negotiable Constraints

## 1. Safety Invariants Matrix

| Safety Invariant | Implementation Mechanism | Enforcement Verification |
|---|---|---|
| `LIVE_TRADING_ENABLED=false` | Global system setting in `packages/common/config.py` | Verified in unit & integration tests (`test_paper_trading_safety_invariants`) |
| `PRIVATE_EXCHANGE_API_ENABLED=false` | Disabled live exchange adapter (`packages/execution/disabled_live_adapter.py`) | Any attempt to call private exchange APIs raises `LiveTradingDisabledException` |
| **No API Keys or Secrets Loaded** | Verification engine checks zero `BINANCE_API_KEY` or `BINANCE_API_SECRET` in paper environment | Env variable audit in test suite |
| **Isolated Paper Account Scope** | Provisioned with unique `account_id` (`PAPER_<session_id>`) | No shared ledger or positions with backtest or live systems |
| **Public-Only Stream Connections** | Runtime connects strictly to unauthenticated public WS `@kline_1h` endpoints | Endpoint URL audit in `packages/paper/market_runtime.py` |
| **No Shorting or Margin** | Deterministic Risk Governor rejects non-LONG intents | Policy check in `packages/risk/governor.py` |
| **No Automatic Production Deployment** | Sessions cannot auto-promote to live trading | Zero automated deployment code paths |

---

## 2. Hard Stop Conditions
- Daily drawdown > 2.0% → Kill switch triggers (`HALTED`).
- Peak drawdown > 5.0% → Kill switch triggers (`HALTED`).
- Public stream clock skew > 5,000ms → Session degrades (`DEGRADED`).
- Unhandled Exception in Pipeline → Session halts cleanly (`HALTED`).
