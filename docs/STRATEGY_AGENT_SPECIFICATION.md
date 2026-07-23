# Strategy Agent Specification

## 1. Overview
Strategy Agents evaluate market conditions independently using `FeatureSnapshot` records and output analytical `AgentSignal` events.

## 2. Implemented Agents
1. **Market Regime Agent (`regime_agent_v1`)**: Classifies market structure into `TREND_UP`, `TREND_DOWN`, `SIDEWAYS`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `TRANSITION`, `LIQUIDITY_RISK`, `UNKNOWN`.
2. **Trend Agent (`trend_agent_v1`)**: Generates `LONG`/`SHORT` analysis signals when market regime is trending (`TREND_UP`/`TREND_DOWN`) with positive/negative EMA slope.
3. **Mean Reversion Agent (`reversion_agent_v1`)**: Operates in `SIDEWAYS`/`LOW_VOLATILITY` regimes, evaluating RSI overbought (>70) and oversold (<30) limits.
4. **Breakout Agent (`breakout_agent_v1`)**: Detects Donchian channel range breakouts confirmed by volume expansion ($RVOL \ge 1.2$).

## 3. Strict Safety Restrictions
- Strategy Agents contain ZERO order placement or trading client dependencies.
- Signals contain NO quantity, notional, leverage, or execution parameters.
- Agents CANNOT emit `order.*` events or trigger trade execution.
