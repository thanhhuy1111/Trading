# Backtest Engine Architecture Specification

## 1. Overview
The Event-Driven Backtest Engine replays historical market data sequentially through the production-safe pipeline without accessing wall-clock time (`datetime.now()`), without modifying production accounts, and without live exchange connections.

```text
Historical Market Data -> Replay Clock -> Data Guardian -> Feature Engine -> Strategy Agents -> Critic Agent -> Consensus/Meta Allocator -> TradeIntent -> Risk Governor -> ApprovedOrder -> Exchange Simulator -> Fills -> Position Manager -> Portfolio Snapshots & Metrics
```

## 2. Invariants & Safety Guarantees
- **No Same-Bar Fill Default**: Order submitted at candle $T$ close is eligible for fill at earliest at $T+1$ open price.
- **Isolated Account Namespace**: All backtest sessions execute under `BACKTEST_<session_id>` account namespace with dedicated subledgers and position managers.
- **Zero Lookahead Leakage**: Signals, features, and risk calculations evaluate strictly on historical data $t \le T_{replay}$.
