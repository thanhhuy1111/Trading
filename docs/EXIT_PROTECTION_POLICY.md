# Exit Protection Policy Specification

## 1. Supported Triggers
- `INITIAL_STOP`: Fixed initial stop price.
- `TAKE_PROFIT`: Target exit price.
- `TRAILING_STOP`: Dynamic trailing stop price.

All exit triggers generate `PositionExitIntent` (`side="SELL"`, `reduce_only=True`).
