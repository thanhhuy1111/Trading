# Portfolio Valuation Specification

## 1. Formulas
$$NAV = CashBalance + AssetMarketValue$$
$$Drawdown\% = \max\left(0, \frac{EquityPeak - NAV}{EquityPeak}\right)$$

## 2. Invariants
- `EquityPeak` is non-decreasing.
- `Drawdown%` is non-negative.
