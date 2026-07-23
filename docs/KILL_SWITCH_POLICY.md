# Kill Switch Policy Specification

## 1. Trigger Conditions
The Kill Switch (`HARD_STOP`) activates automatically when:
1. Daily loss reaches or exceeds `max_daily_loss_pct` (1.50% NAV).
2. Weekly loss reaches or exceeds `max_weekly_loss_pct` (3.50% NAV).
3. Portfolio drawdown reaches or exceeds `hard_stop_drawdown_pct` (8.00% NAV).
4. Portfolio snapshot is stale or corrupted.
5. Manual halt is triggered by an operator.

## 2. Actions on Hard Stop
- All incoming trade intents (`TradeIntent`) are immediately REJECTED with result `HARD_STOPPED`.
- No new `ApprovedOrder` records are created.
- Emits `risk.limit_breached` and `risk.kill_switch_activated` domain events via Transactional Outbox.
- Does NOT automatically reset when PnL recovers (manual recovery confirmation required).
