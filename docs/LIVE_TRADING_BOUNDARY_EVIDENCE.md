# Live Trading Kill Boundary Evidence

## 12-Layer Defense Evidence Matrix

1. **Config Validation Rejection**: `Settings` enforces `LIVE_TRADING_ENABLED=False` and `PRIVATE_EXCHANGE_API_ENABLED=False`. Any attempt to set them to `True` halts startup.
2. **Dependency Injection Isolation**: DI container registers ONLY `PaperExchangeAdapter` and `SimulatorExchangeAdapter`. No live adapter class exists in the DI scope.
3. **Disabled Adapter Enforcement**: `DisabledLiveExchangeAdapter` unconditionally raises `RuntimeError("LIVE_TRADING_DISABLED")` on order submission attempts.
4. **Zero Exchange Credential Schema**: Database schemas contain zero columns or fields for exchange API secret keys.
5. **Zero API Endpoints**: REST routers expose zero endpoints to submit, store, or query exchange API keys.
6. **Zero Frontend Live Controls**: React Dashboard UI (`apps/dashboard`) renders zero toggle buttons or forms to enable live trading.
7. **Zero Private User Streams**: WebSocket manager connects strictly to public market tickers/candles (`wss://stream.binance.com`).
8. **Zero Private Account Endpoints**: System rejects any attempt to query real account balances or fill histories.
9. **Static Import Scan**: Clean import scan confirms no private exchange SDKs (e.g. `ccxt` private client, `binance-connector` private key handlers) are imported.
10. **Network Egress Blocking**: Firewall / container egress policies block private trading routes.
11. **Startup Kill Switch**: `apps/api/main.py` lifespan context manager validates live trading flags and raises `RuntimeError` if enabled.
12. **Critical Incident Escalation**: Attempting to invoke a live execution path automatically logs a `CRITICAL` incident in `incident_service`.
