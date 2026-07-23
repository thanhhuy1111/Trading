# Walk-Forward Evaluation Policy

## 1. Fold Structure
- Train: 60% of fold duration
- Purge Delta: 12-24 hours
- Embargo Delta: 12-24 hours
- Validation: 20% of fold duration
- Test: 20% of fold duration

## 2. Invariants
- `train_end < validation_start < test_start`
- Purge and embargo intervals prevent lookahead leakage across split boundaries.
