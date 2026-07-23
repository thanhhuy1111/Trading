"""Phase 3: registries must exact-match (name, version), enforce valid status transitions
only, and never fuzzy-match compatibility scope."""

import pytest

from packages.domain.enums import RegistryEntryStatus
from packages.registries.instances import (
    evidence_registry,
    feature_artifact_registry,
    label_registry,
    model_registry,
    policy_registry,
    strategy_registry,
    universe_registry,
)
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry, InvalidStatusTransitionError


def test_seven_registries_are_independent_instances() -> None:
    registries = [
        strategy_registry, model_registry, evidence_registry, feature_artifact_registry,
        label_registry, universe_registry, policy_registry,
    ]
    assert len(registries) == 7
    assert len({id(r) for r in registries}) == 7


def test_exact_match_lookup_by_name_and_version() -> None:
    reg = ArtifactRegistry("test")
    entry = RegistryEntry(name="baseline", version="1.0.0")
    reg.register(entry)
    assert reg.get("baseline", "1.0.0") is not None
    assert reg.get("baseline", "1.0.1") is None  # no nearest-version fallback
    assert reg.get("other", "1.0.0") is None


def test_valid_status_transition_updates_entry() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(name="baseline", version="1.0.0", status=RegistryEntryStatus.DRAFT))
    updated = reg.transition_status("baseline", "1.0.0", RegistryEntryStatus.RESEARCH_ONLY)
    assert updated.status == RegistryEntryStatus.RESEARCH_ONLY


def test_invalid_status_transition_is_rejected() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(name="baseline", version="1.0.0", status=RegistryEntryStatus.DRAFT))
    with pytest.raises(InvalidStatusTransitionError):
        # must go through RESEARCH_ONLY/VALIDATED first
        reg.transition_status("baseline", "1.0.0", RegistryEntryStatus.APPROVED)


def test_disabled_and_rejected_are_terminal() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(name="x", version="1.0.0", status=RegistryEntryStatus.REJECTED))
    with pytest.raises(InvalidStatusTransitionError):
        reg.transition_status("x", "1.0.0", RegistryEntryStatus.APPROVED)


def test_transition_of_unknown_entry_raises_key_error() -> None:
    reg = ArtifactRegistry("test")
    with pytest.raises(KeyError):
        reg.transition_status("nonexistent", "1.0.0", RegistryEntryStatus.APPROVED)


def test_universal_entry_matches_any_symbol_and_timeframe() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(name="universal", version="1.0.0"))  # empty scope == universal
    matches = reg.find_compatible(symbol="BTC/USDT", timeframe="1h")
    assert len(matches) == 1


def test_scoped_entry_does_not_match_outside_its_scope() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(
        name="btc_only", version="1.0.0",
        compatible_symbols=["BTC/USDT"], compatible_timeframes=["1h"],
    ))
    assert len(reg.find_compatible(symbol="BTC/USDT", timeframe="1h")) == 1
    assert len(reg.find_compatible(symbol="ETH/USDT", timeframe="1h")) == 0
    assert len(reg.find_compatible(symbol="BTC/USDT", timeframe="4h")) == 0


def test_find_compatible_can_filter_by_status() -> None:
    reg = ArtifactRegistry("test")
    reg.register(RegistryEntry(name="a", version="1.0.0", status=RegistryEntryStatus.DRAFT))
    reg.register(RegistryEntry(name="b", version="1.0.0", status=RegistryEntryStatus.APPROVED))
    approved = reg.find_compatible(status=RegistryEntryStatus.APPROVED)
    assert len(approved) == 1
    assert approved[0].name == "b"
