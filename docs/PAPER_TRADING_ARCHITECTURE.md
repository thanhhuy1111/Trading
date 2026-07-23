# Real-Time Paper Trading System Architecture

## 1. Executive Summary
The Real-Time Paper Trading System (Milestone 10) enables real-time validation of multi-agent strategy pipelines using live public market streams (Binance public WebSocket/REST) and simulated execution adapters without risk to live capital.

---

## 2. Core Architecture Diagram

```mermaid
graph TD
    A[Public Market Stream (WebSocket/REST)] -->|Live Candles & Order Books| B[Data Guardian]
    B -->|Validated Market Data| C[Public Market Runtime]
    C -->|Clock Skew & Gap Audit| D[Warm-up Readiness Gate]
    D -->|Baseline Ready| E[Real-Time Paper Pipeline]
    E -->|Features & Signals| F[Strategy Agents]
    F -->|Strategy Intent| G[Critic Agent & Meta Allocator]
    G -->|TradeIntent| H[Deterministic Risk Governor]
    H -->|Approved Intent| I[Paper Exchange Adapter]
    I -->|Simulated Fills| J[Position Manager & Ledger]
    C -->|Journal Event| K[Durable Event Journal]
    K -->|Checkpoint & State| L[Restart Recovery Engine]
```

---

## 3. Core Components

1. **Paper Trading Session Manager (`packages/paper/session.py`)**: Manages session lifecycle (`CREATED` → `VALIDATING` → `WARMING_UP` → `READY` → `RUNNING` ↔ `PAUSED` | `DEGRADED` | `HALTED` → `STOPPED`), isolated account provisioning (`PAPER_<session_id>`), and immutable configuration snapshots.
2. **Public Market Runtime (`packages/paper/market_runtime.py`)**: Subscribes exclusively to public market streams, measures exchange-to-local clock skew, detects sequence gaps, and triggers automatic REST backfills.
3. **Warm-up Readiness Gate (`packages/paper/warmup.py`)**: Validates historical candle rolling windows, feature calculator warm-up state, regime classification stability, and risk snapshot availability before transitioning a session to `READY`.
4. **Paper Exchange Adapter (`packages/paper/adapter.py`)**: Implements `ExchangeExecutionAdapter` with `ExecutionMode.PAPER`. Simulates order fill pricing with spread, volume participation bounds, latency jitter, taker/maker fee deductions, and idempotency by `client_order_id`.
5. **Real-Time Strategy Pipeline (`packages/paper/pipeline.py`)**: Re-evaluates closed candles through Data Guardian, Feature Engine, Strategy Agents, Critic Agent, Meta Allocator, Risk Governor revalidation, Paper Exchange Adapter, and Position Manager.
6. **Durable Event Journal (`packages/paper/journal.py`)**: Append-only log recording every market event, connection state transition, paper order, fill, and position modification with SHA256 payload checksums.
7. **Restart Recovery Engine (`packages/paper/recovery.py`)**: Restores session state from journal entries and checkpoints upon restart without creating duplicate orders or fills.
8. **Backtest vs. Paper Comparison Engine (`packages/paper/comparison.py`)**: Measures live paper execution drift against historical backtest session baselines.

---

## 4. Key Invariants
- `LIVE_TRADING_ENABLED=false` and `PRIVATE_EXCHANGE_API_ENABLED=false` strictly enforced.
- No live exchange API keys or secrets loaded.
- Dedicated, isolated paper accounts (`PAPER_<session_id>`).
- 100% deterministic risk revalidation via Risk Governor before order placement.
