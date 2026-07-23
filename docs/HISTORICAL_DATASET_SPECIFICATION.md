# Historical Dataset Specification

## 1. Registry & Provenance
Datasets are registered in `packages/backtest/datasets.py` as immutable definitions with SHA256 checksums computed over normalized candle sequences.

## 2. Hard Quality Gates
- All timestamps must be tz-aware UTC.
- Candles must be strictly sorted chronologically.
- Zero duplicate timestamps or missing interval gaps.
- Valid OHLC bounds ($high \ge \max(open, close, low)$, $low \le \min(open, close, high)$).
