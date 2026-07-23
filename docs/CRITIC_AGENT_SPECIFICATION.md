# Critic Agent Specification

## 1. Overview
The Critic Agent is a deterministic, rule-based governance module scrutinizing Strategy Agent signals (`AgentSignal`) prior to aggregation.

## 2. Invariants & Rules
- **Confidence Restriction**: $0 \le adjusted\_confidence \le original\_confidence \le 1$. The Critic Agent CANNOT increase signal confidence under any circumstance.
- **Rule Modules**:
  1. `DataQualityCritic`: Checks feature quality, data guardian health, and timestamp alignment.
  2. `FreshnessCritic`: Enforces `expires_at > current_time` and `generated_at <= current_time`.
  3. `RegimeCompatibilityCritic`: Rejects signals in `LIQUIDITY_RISK` or `UNKNOWN` regimes.
  4. `CostCritic`: Evaluates estimated trading fees, bid-ask spread, slippage, and uncertainty buffer in basis points.
- **Output**: Generates immutable `CriticDecision` records.
