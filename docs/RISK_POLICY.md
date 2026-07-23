# Risk Policy Specification

| Policy Variable | Default Value | Description |
|---|---|---|
| `risk_per_trade_pct` | `0.0025` (0.25% NAV) | Maximum risk budget allocated per trade |
| `max_open_risk_pct` | `0.0100` (1.00% NAV) | Total open risk cap across all positions |
| `max_symbol_allocation_pct` | `0.1500` (15.0% NAV) | Maximum notional allocation allowed for a single symbol |
| `max_total_exposure_pct` | `0.5000` (50.0% NAV) | Gross exposure limit for portfolio |
| `max_daily_loss_pct` | `0.0150` (1.50% NAV) | Daily loss hard limit triggering HARD_STOP |
| `max_weekly_loss_pct` | `0.0350` (3.50% NAV) | Weekly loss hard limit triggering HARD_STOP |
| `hard_stop_drawdown_pct` | `0.0800` (8.00% NAV) | Maximum drawdown threshold triggering Kill Switch |
| `leverage_enabled` | `False` | Leverage strictly prohibited |
| `short_selling_enabled` | `False` | Short selling strictly prohibited in Spot MVP |
| `live_trading_enabled` | `False` | Live trading strictly disabled |
