# AGENT LOGIC MATRIX (Code-Verified)

**All agents are deterministic, rule-based Python. No ML, no randomness, no LLM.** Thresholds are hardcoded in the agent source (not config-driven). Confidence is a fixed constant per branch (`confidence_type="HEURISTIC_SCORE"`). `expected_return_bps` is emitted as `None` by every agent (downstream defaults it to a constant 50 bps).

> ⚠️ **Runtime caveat:** these agents are **not invoked by any runnable pipeline** (see ARCHITECTURE_MAP Island 1). They are exercised only by unit tests. The paper & backtest flows fabricate `TradeIntent`s directly.

## MarketRegimeAgent — `packages/agents/regime.py`
- Inputs: `adx_14`, `ema_20_slope`, `volatility_20`.
- Logic: `vol>0.05 → HIGH_VOLATILITY`; else `adx≥25 & slope>0.001 → TREND_UP`; `adx≥25 & slope<-0.001 → TREND_DOWN`; else `SIDEWAYS`; missing adx/slope → `UNKNOWN`.
- Deterministic ✅. No LLM/ML/random. Cannot place orders. No exchange access.

## TrendAgent — `packages/agents/trend.py`
- Inputs: `market_regime`, `ema_20_slope`.
- BUY(LONG): `regime==TREND_UP & ema_slope>0` → conf **0.75**.
- SELL(SHORT): `regime==TREND_DOWN & ema_slope<0` → conf 0.75 (SHORT blocked downstream).
- Else NO_SIGNAL, conf 0.50.
- ⚠️ `reference_price = Decimal("65000.00")` **hardcoded**; stop/TP/invalidation derived from it (not real price).

## MeanReversionAgent — `packages/agents/reversion.py`
- Inputs: `market_regime`, `rsi_14`, `zscore_20`. Active only if regime ∈ {SIDEWAYS, LOW_VOLATILITY}.
- LONG: `rsi<30 or z<-1.8` → conf **0.70**. SHORT: `rsi>70 or z>1.8` → conf 0.70. Else NO_SIGNAL.
- ⚠️ `reference_price = 65000.00` hardcoded.

## BreakoutAgent — `packages/agents/breakout.py`
- Inputs: `donchian_breakout_20`, `relative_volume_20`.
- LONG: `db>0 & rvol≥1.2` → conf **0.80**. SHORT: `db<0 & rvol≥1.2` → conf 0.80. Else NO_SIGNAL.
- ⚠️ `reference_price = 65000.00` hardcoded.

## CriticAgent — `packages/governance/critic.py`
- Rule-based veto/penalty. Invariant enforced: `0 ≤ adjusted ≤ original ≤ 1` (`governance/models.py::CriticDecision` validator).
- Rejects: expired signal, `regime ∈ {LIQUIDITY_RISK, UNKNOWN}`. Penalties: `expected_bps ≤ cost` (−0.15), `confidence<0.60` (−0.05). Approved if no rejection & `adjusted≥0.40` & action≠NO_SIGNAL.
- Never increases confidence, never creates qty/order. ✅. Uses default `expected_bps=50` when signal has none.

## ConsensusEngine — `packages/governance/consensus.py`
- Confidence-weighted vote of critic-approved signals. Direction LONG/SHORT/FLAT/CONFLICTED (conflict if minority/total > 0.30). `weighted_expected_return_bps` uses per-signal 50 bps default.

## MetaAllocator — `packages/governance/allocator.py`
- `net_edge = weighted_expected_return_bps × weighted_confidence − total_cost_bps`.
- Gates: direction must be LONG/SHORT; net_edge>0; **SHORT → NO_TRADE (`SPOT_SHORT_NOT_EXECUTABLE`)**.
- Emits `TradeIntent(side=BUY, status=PENDING_RISK_REVIEW)` with **no** quantity/notional/leverage (validator forbids those fields). ✅
- ⚠️ `reference_price=65000.00` hardcoded; stop/TP fixed multiples.

## Cost model — `packages/governance/cost_estimator.py`
- All constants: fee 10bps, spread 2bps(BTC)/4bps, slippage 5bps, uncertainty 5bps → total ~22bps. Not market-derived.

## Answers to mandated agent questions
| # | Question | Answer |
|---|---|---|
| 11 | Deterministic? | Yes, all. |
| 12 | Uses random? | No (except `uuid4()` for IDs). |
| 13 | Uses ML model? | No. |
| 14 | Uses LLM? | No. |
| 15 | Computes its own quantity? | No (forbidden by schema). |
| 16 | Can call Execution Engine? | No. |
| 17 | Has exchange client access? | No. |
| 18 | Can bypass Risk Governor? | No (agents produce signals only). |

**Net effect of the "edge":** because `expected_return_bps` is a constant (50/150) and costs are constant (~22), the trade/no-trade decision in the only *runnable* paths reduces to a fixed confidence check (buy when flat). There is no market-predictive alpha in the executed logic.
