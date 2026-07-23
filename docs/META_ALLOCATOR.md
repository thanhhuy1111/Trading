# Meta Allocator Specification

## 1. Scope Restriction
The Meta Allocator allocates **signal influence weights ONLY**. It does NOT allocate capital, money, NAV, or order quantities.

## 2. Net-Edge Calculation
$$NetEdge_{bps} = Return_{weighted\_bps} \times Conf_{weighted} - Fee_{bps} - Spread_{bps} - Slippage_{bps} - Buffer_{bps}$$

## 3. Allocation Decisions
- **Positive Net Edge ($NetEdge_{bps} > 0$)**: Generates `TradeIntent` with side `BUY` and status `PENDING_RISK_REVIEW`.
- **Negative Net Edge or Conflicted**: Generates `AllocationDecision` (`NO_TRADE`).
- **Spot SHORT Signals**: Generates `AllocationDecision` (`NO_TRADE`) with reason code `SPOT_SHORT_NOT_EXECUTABLE`.
