# Reproducibility Policy Specification

## 1. SHA256 Fingerprint Generator
$$Fingerprint = SHA256(DatasetChecksum + Mode + Seed + InitialCash + SameBarFill + CodeVersion + FeatureVersion + RiskVersion)$$

## 2. Invariants
- Replaying the same fingerprint produces identical orders, fills, ledger entries, positions, and final NAV.
