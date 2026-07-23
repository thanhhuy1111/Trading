# Real-Time Risk Revalidation Specification

## 1. Overview
All trade signals generated during Paper Trading MUST pass through the Deterministic Risk Governor (`packages/risk/governor.py`) immediately prior to submission to `PaperExchangeAdapter`.

---

## 2. Risk Snapshot Construction
The paper pipeline constructs a `PortfolioRiskSnapshot` from the session's isolated `PositionManager` and `PortfolioLedger`:
- `account_id`: `PAPER_<session_id>`
- `nav`: Current net asset value (cash + mark-to-market position value)
- `cash_balance`: Available liquid USDT cash
- `gross_exposure`: Sum of open position market values
- `net_exposure`: Net directional position market value
- `open_risk_amount`: Sum of potential dollar loss at stop-loss levels
- `equity_peak`: Peak historical NAV achieved
- `current_drawdown_pct`: `(equity_peak - nav) / equity_peak`

---

## 3. Mandatory Safety Audits
1. **Leverage & Shorting Prohibition**: Leverage > 1.0 or short position intents are rejected with `REJECTED_LEVERAGE_DISALLOWED` or `REJECTED_SHORT_DISALLOWED`.
2. **Maximum Position Count**: Active positions cannot exceed `maximum_positions` (default: 5).
3. **Maximum Notional Cap**: Single position notional cannot exceed `max_position_notional_pct` of NAV.
4. **Daily Loss & Peak Drawdown Limit**: If daily loss exceeds 2% or total drawdown exceeds 5%, Risk Governor triggers Kill Switch (`KILL_SWITCH_ACTIVE`).
5. **No Direct Execution Fields**: `TradeIntent` carries no quantity or execution fields; quantity is calculated deterministically by Risk Governor.
