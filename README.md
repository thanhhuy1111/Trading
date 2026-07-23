# Multi-Agent Cryptocurrency Trading System

A production-grade multi-agent cryptocurrency trading platform featuring a strict **3-Tier Architecture** (Intelligence Agents → Deterministic Risk Governor → Idempotent Execution Engine).

---

## Architecture Overview

```
Market Data
    │
    ▼
Feature Engine
    │
    ▼
Alpha & Context Agents (Regime, Trend, Reversion, Breakout)
    │
    ▼
Critic Agent (Veto & Scrutiny)
    │
    ▼
Meta Allocator (Net Edge & TradeIntent)
    │
    ▼
Risk Governor (Deterministic Sizing & Hard Limits - NO LLM)
    │
    ▼
Execution Engine (State Machine & Idempotent Adapters)
    │
    ▼
Exchange (Binance Spot Testnet / Simulator)
    │
    ▼
Position Manager (SL, TP, Trailing Stop, Signal Decay, Regime Exit)
    │
    ▼
Audit Log (Append-Only)
```

---

## Technology Stack

- **Backend Services**: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy, Alembic, Polars, NumPy.
- **Infrastructure**: PostgreSQL 16, Redis 7, ClickHouse, Redpanda (Kafka-compatible), Docker Compose.
- **Frontend Dashboard**: React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui design tokens.
- **Testing & Quality**: pytest, pytest-asyncio, mypy, ruff, hypothesis.

---

## Quick Start (Milestone 1)

### 1. Prerequisites
Ensure you have Docker & Docker Compose installed, along with Python 3.12+.

### 2. Start Local Infrastructure
Launch PostgreSQL and Redis using the **Minimal Profile** (for local development):
```bash
make infra-minimal
# Or directly:
docker compose --profile minimal up -d postgres redis
```

To launch the **Full Infrastructure Stack** (PostgreSQL, Redis, ClickHouse, Redpanda):
```bash
make infra-full
# Or directly:
docker compose --profile full up -d
```

### 3. Run Backend API Server
Install Python dependencies and start FastAPI server:
```bash
pip install -e .[dev]
make dev-api
# Server listens on http://localhost:8000
# OpenAPI Docs: http://localhost:8000/docs
```

### 4. Run Frontend Dashboard
```bash
cd apps/dashboard
npm install
npm run dev
# Open browser at http://localhost:5173
```

### 5. Run Database Migrations
```bash
make migrate
```

### 6. Run Test Suite & Code Quality Checks
```bash
make test
make lint
make typecheck
```

---

## Monorepo Layout

- `apps/api`: FastAPI REST & WebSocket server.
- `apps/dashboard`: React + Vite interactive operational dashboard.
- `services/`: Core microservices (market-data, feature-engine, risk-engine, execution-engine, etc.).
- `packages/schemas`: Shared Pydantic domain models (`MarketTick`, `TradeIntent`, `RiskDecision`, `Position`, `AuditEvent`).
- `packages/common`: Global configuration settings and structured logger.
- `infra/migrations`: Alembic database migration versions.
- `tests/`: Unit, integration, property-based, and simulation test suites.
