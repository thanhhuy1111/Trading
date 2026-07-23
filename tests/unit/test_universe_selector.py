"""Phase 4: universe eligibility must be pure/offline and deterministic. No network calls in
this file — packages/universe/live_source.py is exercised separately, opt-in only."""

from datetime import datetime, timezone
from decimal import Decimal

from packages.universe.models import ExclusionReason, SymbolMetadata, UniverseSelectionRules
from packages.universe.selector import build_universe_snapshot, evaluate_symbol


def _good_metadata(**overrides) -> SymbolMetadata:
    base = dict(
        symbol="BTC/USDT", exchange_symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        status="TRADING", is_spot_trading_allowed=True, history_days_available=1000,
        quote_volume_24h_usdt=Decimal("500000000"), recent_candle_completeness_pct=Decimal("100"),
        best_bid=Decimal("50000.00"), best_ask=Decimal("50002.00"),
    )
    base.update(overrides)
    return SymbolMetadata(**base)


def test_eligible_symbol_passes_all_checks() -> None:
    ev = evaluate_symbol(_good_metadata(), UniverseSelectionRules())
    assert ev.eligible is True
    assert ev.exclusion_reasons == []


def test_non_usdt_quote_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(quote_asset="BTC", symbol="ETH/BTC"), UniverseSelectionRules())
    assert ev.eligible is False
    assert ExclusionReason.NOT_USDT_QUOTED in ev.exclusion_reasons


def test_stablecoin_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(base_asset="USDC", symbol="USDC/USDT"), UniverseSelectionRules())
    assert ExclusionReason.IS_STABLECOIN in ev.exclusion_reasons


def test_leveraged_token_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(base_asset="BTCUP", symbol="BTCUP/USDT"), UniverseSelectionRules())
    assert ExclusionReason.IS_LEVERAGED_TOKEN in ev.exclusion_reasons


def test_delisted_symbol_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(status="BREAK"), UniverseSelectionRules())
    assert ExclusionReason.DELISTED_OR_HALTED in ev.exclusion_reasons


def test_spot_disabled_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(is_spot_trading_allowed=False), UniverseSelectionRules())
    assert ExclusionReason.NOT_SPOT_TRADING_ENABLED in ev.exclusion_reasons


def test_insufficient_history_excluded() -> None:
    rules = UniverseSelectionRules(min_history_days=730)
    ev = evaluate_symbol(_good_metadata(history_days_available=100), rules)
    assert ExclusionReason.INSUFFICIENT_HISTORY in ev.exclusion_reasons


def test_missing_history_treated_as_insufficient() -> None:
    ev = evaluate_symbol(_good_metadata(history_days_available=None), UniverseSelectionRules())
    assert ExclusionReason.INSUFFICIENT_HISTORY in ev.exclusion_reasons


def test_low_quote_volume_excluded() -> None:
    rules = UniverseSelectionRules(min_quote_volume_24h_usdt=Decimal("10000000"))
    ev = evaluate_symbol(_good_metadata(quote_volume_24h_usdt=Decimal("1000000")), rules)
    assert ExclusionReason.INSUFFICIENT_QUOTE_VOLUME in ev.exclusion_reasons


def test_low_data_completeness_excluded() -> None:
    ev = evaluate_symbol(_good_metadata(recent_candle_completeness_pct=Decimal("50")), UniverseSelectionRules())
    assert ExclusionReason.INSUFFICIENT_DATA_COMPLETENESS in ev.exclusion_reasons


def test_wide_spread_excluded() -> None:
    # (50100-49900)/50000 = 400 bps, well above the 15 bps default max
    ev = evaluate_symbol(_good_metadata(best_bid=Decimal("49900"), best_ask=Decimal("50100")), UniverseSelectionRules())
    assert ExclusionReason.EXCESSIVE_SPREAD in ev.exclusion_reasons


def test_missing_spread_data_fails_closed() -> None:
    """No bid/ask available -> liquidity can't be verified -> excluded, never silently assumed
    tradeable."""
    ev = evaluate_symbol(_good_metadata(best_bid=None, best_ask=None), UniverseSelectionRules())
    assert ExclusionReason.EXCESSIVE_SPREAD in ev.exclusion_reasons


def test_unavailable_metadata_excluded_with_single_reason() -> None:
    md = SymbolMetadata(
        symbol="XYZ/USDT", exchange_symbol="XYZUSDT", base_asset="XYZ", quote_asset="USDT",
        status="UNKNOWN", is_spot_trading_allowed=False, metadata_available=False,
    )
    ev = evaluate_symbol(md, UniverseSelectionRules())
    assert ev.eligible is False
    assert ev.exclusion_reasons == [ExclusionReason.METADATA_UNAVAILABLE]


def test_snapshot_is_deterministic_and_checksummed() -> None:
    metadata = [_good_metadata(), _good_metadata(symbol="ETH/USDT", exchange_symbol="ETHUSDT", base_asset="ETH")]
    rules = UniverseSelectionRules()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

    snap1 = build_universe_snapshot(metadata, rules, generated_at=ts)
    snap2 = build_universe_snapshot(metadata, rules, generated_at=ts)

    assert snap1.metadata_checksum == snap2.metadata_checksum
    assert snap1.eligible_symbols == ["BTC/USDT", "ETH/USDT"]
    assert snap1.excluded_symbols == []


def test_snapshot_separates_eligible_and_excluded_with_reasons() -> None:
    metadata = [
        _good_metadata(),
        _good_metadata(symbol="USDC/USDT", exchange_symbol="USDCUSDT", base_asset="USDC"),
    ]
    snapshot = build_universe_snapshot(metadata, UniverseSelectionRules())
    assert snapshot.eligible_symbols == ["BTC/USDT"]
    assert snapshot.excluded_symbols == ["USDC/USDT"]
    assert "IS_STABLECOIN" in snapshot.exclusion_reasons["USDC/USDT"]
