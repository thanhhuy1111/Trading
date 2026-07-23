# Backtest Metrics Specification

## 1. Primary Metrics
- `Net Profit` = $FinalNAV - InitialNAV$
- `Total Return %` = $\frac{NetProfit}{InitialNAV} \times 100$
- `Annualized Return %` = $((FinalNAV / InitialNAV)^{365/Days} - 1) \times 100$
- `Max Drawdown %` = $\max\left(\frac{Peak - NAV}{Peak}\right) \times 100$
- `Win Rate %` = $\frac{WinningTrades}{TotalTrades} \times 100$
- `Profit Factor` = $\frac{GrossWins}{GrossLosses}$
