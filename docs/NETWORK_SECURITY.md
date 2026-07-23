# Network Security Policy

## Network Boundaries
- Public Internet Egress: Allowed ONLY to public market data WebSocket endpoints (`wss://stream.binance.com`).
- Private Egress: Strictly blocked to private exchange order APIs (`LIVE_TRADING_ENABLED=false`).
- PostgreSQL & Redis: Internal Docker network binding only (`0.0.0.0` public exposure prohibited).
