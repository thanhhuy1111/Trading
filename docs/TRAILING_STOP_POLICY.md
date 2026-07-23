# Trailing Stop Policy Specification

## 1. Formula
$$CandidateTrailing = High_{valid} \times (1 - TrailingDistance\%)$$
$$Stop_{trailing} = \max\left(Stop_{prev}, CandidateTrailing, Stop_{init}\right)$$

## 2. Invariants
- Trailing stop price can ONLY increase or stay constant; it NEVER decreases.
