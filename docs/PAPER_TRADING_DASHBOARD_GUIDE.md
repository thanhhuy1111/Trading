# Real-Time Paper Trading Dashboard Guide

## 1. Overview
The Real-Time Paper Trading Panel in the React Dashboard (`apps/dashboard/src/App.tsx`) provides real-time monitoring and interactive control over active paper trading sessions.

---

## 2. Interface Features
- **Session Status Badge**: Displays current state (`RUNNING`, `WARMING_UP`, `READY`, `PAUSED`, `DEGRADED`, `HALTED`).
- **Simulated Portfolio Balance**: Real-time NAV, cash balance, and percentage total return.
- **Public Data Health**: Live WebSocket connection latency, ping state, and clock skew in milliseconds.
- **Risk Revalidation Gate**: Pass/fail status of Deterministic Risk Governor evaluations.
- **Interactive Controls**:
  - `START SYSTEM`: Launches session validation, warm-up, and paper pipeline.
  - `PAUSE`: Temporarily pauses closed-candle signal processing.
  - `STOP SESSION`: Gracefully cancels pending paper orders and stops session.
  - `RECOVERY CHECKPOINT`: Triggers manual durable event journal recovery check.
