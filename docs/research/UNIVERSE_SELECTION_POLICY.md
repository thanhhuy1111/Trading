# Dynamic Trading Universe — Selection Policy

## Purpose

Before any symbol beyond BTC/USDT and ETH/USDT is eligible for research or (eventually) a
trade proposal, it must pass a deterministic, versioned set of eligibility checks. This
policy — and its implementation in `packages/universe/` — defines exactly what those checks
are and separates the parts that must stay offline-testable from the one part that touches
the network.

## Architecture

- `packages/universe/models.py` — `SymbolMetadata` (the inputs the selector needs),
  `UniverseSelectionRules` (versioned thresholds), `ExclusionReason`, `UniverseSnapshot`.
- `packages/universe/selector.py` — **pure function** `evaluate_symbol` /
  `build_universe_snapshot`. Takes already-fetched `SymbolMetadata`, does no I/O. This is what
  the default test suite exercises (`tests/unit/test_universe_selector.py`, 15 tests, all
  offline with fixture data).
- `packages/universe/live_source.py` — the only module that calls the network
  (`data-api.binance.vision`, the same public Binance data mirror used by
  `packages/research/data_fetcher.py` — `api.binance.com` is geo-blocked in this environment).
  Never imported by anything that runs automatically.
- `packages/universe/build_snapshot.py` — opt-in CLI entrypoint
  (`python -m packages.universe.build_snapshot`) that wires `live_source` → `selector` and
  writes the snapshot. A human or a scheduled job must explicitly run this; it is not part of
  `pytest`.

## Seed universe

```
BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LINKUSDT, AVAXUSDT
```

## Eligibility checks (`UniverseSelectionRules`, version `universe_v1`)

| Check | Rule | Exclusion reason |
|---|---|---|
| Spot trading enabled | `isSpotTradingAllowed == true` (Binance exchangeInfo) | `NOT_SPOT_TRADING_ENABLED` |
| USDT-quoted | `quoteAsset == "USDT"` | `NOT_USDT_QUOTED` |
| Not a stablecoin | `baseAsset` not in a manually-reviewed stablecoin list (USDC, BUSD, TUSD, DAI, FDUSD, USDP, USTC, GUSD, EURT, PYUSD) | `IS_STABLECOIN` |
| Not a leveraged token | `baseAsset` doesn't end in `UP`/`DOWN`/`BULL`/`BEAR` (Binance leveraged-token naming) | `IS_LEVERAGED_TOKEN` |
| Not delisted/halted | `status == "TRADING"` | `DELISTED_OR_HALTED` |
| Sufficient history | ≥ 730 days of daily candle history available | `INSUFFICIENT_HISTORY` |
| Sufficient quote volume | 24h quote volume ≥ $10,000,000 USDT | `INSUFFICIENT_QUOTE_VOLUME` |
| Data completeness | ≥ 95% of expected daily candles present over the trailing 30 days (no silent gap-filling — missing means missing) | `INSUFFICIENT_DATA_COMPLETENESS` |
| Liquidity proxy | Bid/ask spread ≤ 15 bps of mid price | `EXCESSIVE_SPREAD` |

A symbol whose metadata couldn't be fetched at all is excluded with `METADATA_UNAVAILABLE`
rather than silently skipped. A symbol with no bid/ask data fails the spread check closed
(`EXCESSIVE_SPREAD`) rather than being assumed liquid — see `test_missing_spread_data_fails_closed`.

Every symbol is evaluated independently and can carry multiple exclusion reasons at once.

## Snapshot determinism

`UniverseSnapshot.metadata_checksum` is a SHA-256 over the version, rules, and sorted
eligible/excluded symbol lists — the same metadata always produces the same checksum, and any
change to a symbol's status or the rules themselves changes it. `build_universe_snapshot` is
pure given its `SymbolMetadata` inputs (`test_snapshot_is_deterministic_and_checksummed`).

## Result of the current live snapshot

`docs/research/experiments/UNIVERSE_SNAPSHOT.json` (real data, fetched once via
`python -m packages.universe.build_snapshot`):

| Eligible | Excluded | Reason |
|---|---|---|
| BTC/USDT, ETH/USDT, BNB/USDT, SOL/USDT, XRP/USDT, ADA/USDT, DOGE/USDT | — | — |
| — | LINK/USDT | `INSUFFICIENT_QUOTE_VOLUME` (24h quote volume below the $10M threshold at fetch time) |
| — | AVAX/USDT | `INSUFFICIENT_QUOTE_VOLUME` |

This snapshot only determines *eligibility* for future research. It is **not** evidence that
any of these 7 symbols would pass the promotion gate — see `ASSET_SPECIFIC_EVIDENCE_POLICY.md`
and `BTC_ETH_FAILURE_ANALYSIS.md` for why passing on one symbol (or being in this list at all)
says nothing about another symbol's result. No multi-asset campaign (Phase 13) has been run
against this universe in this checkpoint.

## Refresh policy

Live refresh is opt-in and manual for now. `UniverseSnapshot.generated_at` records when a
snapshot was produced; a consumer should treat a snapshot as stale after some operationally
reasonable window (not yet enforced automatically — this is a Phase 19/continuous-monitoring
concern, out of scope for this checkpoint) and re-run `build_snapshot` rather than trusting an
old one indefinitely, since 24h volume and spread are point-in-time measurements.
