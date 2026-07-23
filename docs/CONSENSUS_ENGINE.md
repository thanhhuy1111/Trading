# Signal Consensus Engine Specification

## 1. Overview
The `SignalConsensusEngine` aggregates accepted `CriticDecision` records and corresponding `AgentSignal` outputs across multiple strategy agents.

## 2. Metrics & Outputs
- **Agreement Score**: $max(LongVotes, ShortVotes) / TotalVotes$
- **Disagreement Score**: $min(LongVotes, ShortVotes) / TotalVotes$
- **Weighted Confidence**: Mean adjusted confidence of participating accepted signals.
- **Direction Vote**: `LONG`, `SHORT`, `FLAT`, `CONFLICTED`, or `INSUFFICIENT_EVIDENCE`.
