"""Pure universe eligibility evaluation. No network calls — takes already-fetched
SymbolMetadata and applies UniverseSelectionRules deterministically. This is what default
(offline) tests exercise; live_source.py is the only piece that ever calls the network."""

from datetime import datetime, timezone
from typing import List

from packages.universe.models import (
    KNOWN_STABLECOIN_BASE_ASSETS,
    LEVERAGED_TOKEN_SUFFIXES,
    ExclusionReason,
    SymbolEvaluation,
    SymbolMetadata,
    UniverseSelectionRules,
    UniverseSnapshot,
)


def evaluate_symbol(metadata: SymbolMetadata, rules: UniverseSelectionRules) -> SymbolEvaluation:
    reasons: List[ExclusionReason] = []

    if not metadata.metadata_available:
        return SymbolEvaluation(
            symbol=metadata.symbol, eligible=False,
            exclusion_reasons=[ExclusionReason.METADATA_UNAVAILABLE], metadata=metadata,
        )

    if metadata.quote_asset != "USDT":
        reasons.append(ExclusionReason.NOT_USDT_QUOTED)

    if metadata.base_asset in KNOWN_STABLECOIN_BASE_ASSETS:
        reasons.append(ExclusionReason.IS_STABLECOIN)

    if any(metadata.base_asset.endswith(suffix) for suffix in LEVERAGED_TOKEN_SUFFIXES):
        reasons.append(ExclusionReason.IS_LEVERAGED_TOKEN)

    if metadata.status != "TRADING":
        reasons.append(ExclusionReason.DELISTED_OR_HALTED)

    if not metadata.is_spot_trading_allowed:
        reasons.append(ExclusionReason.NOT_SPOT_TRADING_ENABLED)

    if metadata.history_days_available is None or metadata.history_days_available < rules.min_history_days:
        reasons.append(ExclusionReason.INSUFFICIENT_HISTORY)

    if (
        metadata.quote_volume_24h_usdt is None
        or metadata.quote_volume_24h_usdt < rules.min_quote_volume_24h_usdt
    ):
        reasons.append(ExclusionReason.INSUFFICIENT_QUOTE_VOLUME)

    if (
        metadata.recent_candle_completeness_pct is None
        or metadata.recent_candle_completeness_pct < rules.min_recent_candle_completeness_pct
    ):
        reasons.append(ExclusionReason.INSUFFICIENT_DATA_COMPLETENESS)

    if metadata.best_bid is not None and metadata.best_ask is not None and metadata.best_bid > 0:
        mid = (metadata.best_bid + metadata.best_ask) / 2
        spread_bps = ((metadata.best_ask - metadata.best_bid) / mid) * 10000
        if spread_bps > rules.max_spread_bps:
            reasons.append(ExclusionReason.EXCESSIVE_SPREAD)
    else:
        reasons.append(ExclusionReason.EXCESSIVE_SPREAD)  # can't verify liquidity -> fail closed

    return SymbolEvaluation(
        symbol=metadata.symbol, eligible=(len(reasons) == 0),
        exclusion_reasons=reasons, metadata=metadata,
    )


def build_universe_snapshot(
    metadata_list: List[SymbolMetadata],
    rules: UniverseSelectionRules,
    generated_at: datetime = None,
) -> UniverseSnapshot:
    generated_at = generated_at or datetime.now(timezone.utc)
    evaluations = [evaluate_symbol(m, rules) for m in metadata_list]

    eligible = sorted(e.symbol for e in evaluations if e.eligible)
    excluded = sorted(e.symbol for e in evaluations if not e.eligible)
    reasons_map = {e.symbol: [r.value for r in e.exclusion_reasons] for e in evaluations if not e.eligible}

    snapshot = UniverseSnapshot(
        generated_at=generated_at,
        selection_rules=rules,
        eligible_symbols=eligible,
        excluded_symbols=excluded,
        exclusion_reasons=reasons_map,
    )
    snapshot.metadata_checksum = snapshot.compute_checksum()
    return snapshot
