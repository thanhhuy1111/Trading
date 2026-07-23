# Governance Policy Specification

## 1. Safety & Authority Boundaries
- **Strategy Agents**: Generate `AgentSignal` ONLY.
- **Critic Agent**: Scrutinizes signals, applies penalties, generates `CriticDecision`. Cannot increase confidence.
- **Signal Consensus Engine**: Computes directional agreement and weighted return.
- **Meta Allocator**: Computes Net Edge and signal weights. Generates `TradeIntent` with status `PENDING_RISK_REVIEW` or `AllocationDecision` (`NO_TRADE`). Cannot size positions or submit orders.
- **Risk Governor**: (Milestone 6) Evaluates NAV risk, position limits, and computes quantity.
- **Execution Engine**: (Milestone 7) Places orders on exchange.
