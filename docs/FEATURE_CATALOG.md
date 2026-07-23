# Feature Catalog Specification

| Feature Name | Category | Version | Formula / Description | Required Lookback | Output Type | Range |
|---|---|---|---|---|---|---|
| `return_1p` | price_return | 1.0.0 | $(P_t - P_{t-1}) / P_{t-1}$ | 2 bars | Decimal | $(-\infty, +\infty)$ |
| `return_3p` | price_return | 1.0.0 | $(P_t - P_{t-3}) / P_{t-3}$ | 4 bars | Decimal | $(-\infty, +\infty)$ |
| `return_5p` | price_return | 1.0.0 | $(P_t - P_{t-5}) / P_{t-5}$ | 6 bars | Decimal | $(-\infty, +\infty)$ |
| `high_low_range` | price_return | 1.0.0 | $(High_t - Low_t) / Low_t$ | 1 bar | Decimal | $[0, +\infty)$ |
| `sma_10` | trend | 1.0.0 | 10-period Simple Moving Average | 10 bars | Decimal | $(0, +\infty)$ |
| `sma_20` | trend | 1.0.0 | 20-period Simple Moving Average | 20 bars | Decimal | $(0, +\infty)$ |
| `ema_10` | trend | 1.0.0 | 10-period Exponential Moving Average | 10 bars | Decimal | $(0, +\infty)$ |
| `ema_20` | trend | 1.0.0 | 20-period Exponential Moving Average | 20 bars | Decimal | $(0, +\infty)$ |
| `ema_20_slope` | trend | 1.0.0 | $(EMA_{20,t} - EMA_{20,t-3}) / EMA_{20,t-3}$ | 23 bars | Decimal | $(-\infty, +\infty)$ |
| `adx_14` | trend | 1.0.0 | 14-period Average Directional Index | 28 bars | Decimal | $[0, 100]$ |
| `rsi_14` | momentum | 1.0.0 | 14-period Relative Strength Index | 15 bars | Decimal | $[0, 100]$ |
| `atr_14` | volatility | 1.0.0 | 14-period Average True Range | 15 bars | Decimal | $[0, +\infty)$ |
| `volatility_20` | volatility | 1.0.0 | 20-period Realized Volatility (StdDev) | 21 bars | Decimal | $[0, +\infty)$ |
| `volume_sma_20` | volume | 1.0.0 | 20-period Volume SMA | 20 bars | Decimal | $[0, +\infty)$ |
| `relative_volume_20` | volume | 1.0.0 | $Volume_t / VolumeSMA_{20}$ | 20 bars | Decimal | $[0, +\infty)$ |
| `zscore_20` | mean_reversion | 1.0.0 | 20-period Price Rolling Z-Score | 20 bars | Decimal | $(-\infty, +\infty)$ |
| `bollinger_pos_20` | mean_reversion | 1.0.0 | Bollinger Band %B position | 20 bars | Decimal | $(-\infty, +\infty)$ |
| `donchian_breakout_20` | breakout | 1.0.0 | Donchian Channel 20-period breakout (+1/-1/0) | 21 bars | Decimal | $\{-1.0, 0.0, 1.0\}$ |
