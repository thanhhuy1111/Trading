from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.agents.advanced import (
    AdvancedAgentCoordinator,
    AdvancedAvailability,
    AdvancedEvidenceRegistry,
    AdvancedFeatureFlags,
    AdvancedProviderResult,
    AdvancedResearchProposalGate,
    AdvancedSourceKind,
    AdvancedSourceObservation,
    AdvancedSourceRequest,
    AdvancedSourceService,
    AssetModelBinding,
    AssetModelBindingRegistry,
    DataQuality,
    DynamicWeightProposal,
    ReflectionProposal,
    SourceLicenseRegistry,
)
from packages.common.config import settings
from packages.common.immutable import FrozenMapping


class _Provider:
    def __init__(self, result: AdvancedProviderResult) -> None:
        self.result = result
        self.calls = 0

    async def fetch(self, request: AdvancedSourceRequest) -> AdvancedProviderResult:
        self.calls += 1
        return self.result


def _observation(
    kind: AdvancedSourceKind,
    as_of: datetime,
    *,
    available_at: datetime | None = None,
    received_at: datetime | None = None,
    quality: DataQuality = DataQuality.HEALTHY,
) -> AdvancedSourceObservation:
    available = available_at or as_of - timedelta(minutes=5)
    observed = as_of - timedelta(minutes=10)
    source_time = (observed - timedelta(minutes=1)).isoformat()
    values = {
        AdvancedSourceKind.NEWS: {
            "headline_hash": "a" * 64,
            "published_at": source_time,
            "relevance_score": "0.5",
            "relevance_unit": "probability",
        },
        AdvancedSourceKind.ONCHAIN: {
            "metric_name": "active_addresses",
            "metric_value": "100",
            "metric_unit": "addresses",
            "block_time": source_time,
        },
        AdvancedSourceKind.MACRO: {
            "series_id": "CPI",
            "value": "2.5",
            "unit": "percent",
            "release_time": source_time,
            "revision": "initial",
        },
        AdvancedSourceKind.SENTIMENT: {
            "score": "0.1",
            "unit": "normalized_score",
            "sample_window": "1h",
            "window_end": source_time,
        },
        AdvancedSourceKind.MARKET_REGIME: {
            "regime": "NEUTRAL",
            "methodology_version": "regime_v1",
            "window_start": (observed - timedelta(hours=1)).isoformat(),
            "window_end": source_time,
        },
    }[kind]
    return AdvancedSourceObservation(
        kind=kind,
        provider_id=f"mock-{kind.value.lower()}",
        provider_version="1.0.0",
        license_id="TEST_FIXTURE_LICENSE",
        source_record_id="fixture-1",
        provenance_uri="https://fixtures.example.test/records/fixture-1",
        symbol="BTCUSDT",
        observed_at=observed,
        available_at=available,
        received_at=received_at or max(as_of, available),
        quality=quality,
        values=FrozenMapping(values),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "flag_name"),
    [
        (AdvancedSourceKind.NEWS, "news"),
        (AdvancedSourceKind.ONCHAIN, "onchain"),
        (AdvancedSourceKind.MACRO, "macro"),
        (AdvancedSourceKind.SENTIMENT, "sentiment"),
        (AdvancedSourceKind.MARKET_REGIME, "market_regime"),
    ],
)
async def test_advanced_sources_mock_contract_and_evidence(
    kind: AdvancedSourceKind,
    flag_name: str,
) -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observation = _observation(kind, as_of)
    provider = _Provider(
        AdvancedProviderResult(
            availability=AdvancedAvailability.AVAILABLE,
            observation=observation,
        )
    )
    flags = AdvancedFeatureFlags(**{flag_name: True})
    licenses = SourceLicenseRegistry()
    registry = AdvancedEvidenceRegistry(licenses)
    licenses.allow(
        kind,
        observation.provider_id,
        observation.license_id,
        allowed_domains=("fixtures.example.test",),
        retention_days=30,
    )
    service = AdvancedSourceService(
        flags=flags,
        providers=FrozenMapping({kind: provider}),
        evidence=registry,
        licenses=licenses,
    )

    result = await service.analyze(
        AdvancedSourceRequest(
            analysis_id=f"analysis-{kind.value}",
            kind=kind,
            symbol="BTCUSDT",
            as_of_time=as_of,
        )
    )

    assert result.status == AdvancedAvailability.AVAILABLE
    assert result.evidence is not None
    assert result.evidence.license_id == "TEST_FIXTURE_LICENSE"
    assert registry.get(result.evidence.evidence_id) == result.evidence


@pytest.mark.asyncio
async def test_disabled_unconfigured_future_and_bad_quality_fail_closed() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    kind = AdvancedSourceKind.NEWS
    provider = _Provider(
        AdvancedProviderResult(
            availability=AdvancedAvailability.AVAILABLE,
            observation=_observation(kind, as_of),
        )
    )
    request = AdvancedSourceRequest(
        analysis_id="analysis-disabled",
        kind=kind,
        symbol="BTCUSDT",
        as_of_time=as_of,
    )
    disabled_licenses = SourceLicenseRegistry()
    disabled = AdvancedSourceService(
        flags=AdvancedFeatureFlags(),
        providers=FrozenMapping({kind: provider}),
        evidence=AdvancedEvidenceRegistry(disabled_licenses),
        licenses=disabled_licenses,
    )
    result = await disabled.analyze(request)
    assert result.reason_codes == ("ADVANCED_FEATURE_DISABLED",)
    assert provider.calls == 0

    unconfigured_licenses = SourceLicenseRegistry()
    unconfigured = AdvancedSourceService(
        flags=AdvancedFeatureFlags(news=True),
        providers=FrozenMapping({}),
        evidence=AdvancedEvidenceRegistry(unconfigured_licenses),
        licenses=unconfigured_licenses,
    )
    assert (await unconfigured.analyze(request)).reason_codes == (
        "ADVANCED_PROVIDER_NOT_CONFIGURED",
    )

    for observation, reason in (
        (
            _observation(kind, as_of, available_at=as_of + timedelta(seconds=1)),
            "ADVANCED_LOOKAHEAD_REJECTED",
        ),
        (
            _observation(kind, as_of, quality=DataQuality.DEGRADED),
            "ADVANCED_DATA_QUALITY_REJECTED",
        ),
        (
            _observation(
                kind,
                as_of,
                received_at=as_of + timedelta(seconds=1),
            ),
            "ADVANCED_LOOKAHEAD_REJECTED",
        ),
    ):
        licenses = SourceLicenseRegistry()
        licenses.allow(
            kind,
            observation.provider_id,
            observation.license_id,
            allowed_domains=("fixtures.example.test",),
            retention_days=30,
        )
        service = AdvancedSourceService(
            flags=AdvancedFeatureFlags(news=True),
            providers=FrozenMapping(
                {
                    kind: _Provider(
                        AdvancedProviderResult(
                            availability=AdvancedAvailability.AVAILABLE,
                            observation=observation,
                        )
                    )
                }
            ),
            evidence=AdvancedEvidenceRegistry(licenses),
            licenses=licenses,
        )
        assert (await service.analyze(request)).reason_codes == (reason,)

    unlicensed_observation = _observation(kind, as_of)
    unlicensed_licenses = SourceLicenseRegistry()
    unlicensed = AdvancedSourceService(
        flags=AdvancedFeatureFlags(news=True),
        providers=FrozenMapping(
            {
                kind: _Provider(
                    AdvancedProviderResult(
                        availability=AdvancedAvailability.AVAILABLE,
                        observation=unlicensed_observation,
                    )
                )
            }
        ),
        evidence=AdvancedEvidenceRegistry(unlicensed_licenses),
        licenses=unlicensed_licenses,
    )
    assert (await unlicensed.analyze(request)).reason_codes == (
        "ADVANCED_LICENSE_REJECTED",
    )

    class _MalformedProvider:
        async def fetch(self, request):
            return None

    malformed_licenses = SourceLicenseRegistry()
    malformed = AdvancedSourceService(
        flags=AdvancedFeatureFlags(news=True),
        providers=FrozenMapping({kind: _MalformedProvider()}),
        evidence=AdvancedEvidenceRegistry(malformed_licenses),
        licenses=malformed_licenses,
    )
    assert (await malformed.analyze(request)).reason_codes == (
        "ADVANCED_PROVIDER_ERROR",
    )


def test_eth_model_binding_has_no_btc_fallback() -> None:
    disabled_registry = AssetModelBindingRegistry()
    disabled_registry.register(
        AssetModelBinding(
            symbol="ETHUSDT",
            model_id="eth-disabled",
            model_version="1",
            artifact_checksum="c" * 64,
            training_symbol="ETHUSDT",
            timeframe="4h",
            feature_schema_version="eth_features_v1",
        )
    )
    assert disabled_registry.resolve("ETHUSDT") is None

    registry = AssetModelBindingRegistry(flags=AdvancedFeatureFlags(eth=True))
    btc = registry.register(
        AssetModelBinding(
            symbol="BTCUSDT",
            model_id="btc-xgb",
            model_version="1",
            artifact_checksum="a" * 64,
            training_symbol="BTCUSDT",
            timeframe="4h",
            feature_schema_version="btc_features_v1",
        )
    )
    assert registry.resolve("BTCUSDT") == btc
    assert registry.resolve("ETHUSDT") is None

    eth = registry.register(
        AssetModelBinding(
            symbol="ETHUSDT",
            model_id="eth-xgb",
            model_version="1",
            artifact_checksum="b" * 64,
            training_symbol="ETHUSDT",
            timeframe="4h",
            feature_schema_version="eth_features_v1",
        )
    )
    assert registry.resolve("ETHUSDT") == eth
    assert registry.resolve("ETHUSDT").model_id != btc.model_id  # type: ignore[union-attr]
    duplicate_model = AssetModelBindingRegistry(flags=AdvancedFeatureFlags(eth=True))
    duplicate_model.register(btc)
    with pytest.raises(ValueError, match="ASSET_MODEL_CROSS_SYMBOL_REUSE"):
        duplicate_model.register(
            AssetModelBinding(
                symbol="ETHUSDT",
                model_id=btc.model_id,
                model_version=btc.model_version,
                artifact_checksum="d" * 64,
                training_symbol="ETHUSDT",
                timeframe="4h",
                feature_schema_version="eth_features_v1",
            )
        )
    duplicate_artifact = AssetModelBindingRegistry(flags=AdvancedFeatureFlags(eth=True))
    duplicate_artifact.register(btc)
    with pytest.raises(ValueError, match="ASSET_MODEL_ARTIFACT_CROSS_SYMBOL_REUSE"):
        duplicate_artifact.register(
            AssetModelBinding(
                symbol="ETHUSDT",
                model_id="renamed-eth",
                model_version="different",
                artifact_checksum=btc.artifact_checksum,
                training_symbol="ETHUSDT",
                timeframe="4h",
                feature_schema_version="eth_features_v1",
            )
        )


@pytest.mark.asyncio
async def test_reflection_and_dynamic_weights_are_research_only_proposals() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observation = _observation(AdvancedSourceKind.NEWS, as_of)
    licenses = SourceLicenseRegistry()
    licenses.allow(
        AdvancedSourceKind.NEWS,
        observation.provider_id,
        observation.license_id,
        allowed_domains=("fixtures.example.test",),
        retention_days=30,
    )
    evidence_registry = AdvancedEvidenceRegistry(licenses)
    analysis = await AdvancedSourceService(
        flags=AdvancedFeatureFlags(news=True),
        providers=FrozenMapping(
            {
                AdvancedSourceKind.NEWS: _Provider(
                    AdvancedProviderResult(
                        availability=AdvancedAvailability.AVAILABLE,
                        observation=observation,
                    )
                )
            }
        ),
        evidence=evidence_registry,
        licenses=licenses,
    ).analyze(
        AdvancedSourceRequest(
            analysis_id="analysis-1",
            kind=AdvancedSourceKind.NEWS,
            symbol="BTCUSDT",
            as_of_time=as_of,
        )
    )
    assert analysis.evidence is not None
    evidence_id = analysis.evidence.evidence_id
    reflection = ReflectionProposal(
        proposal_id="reflection-1",
        analysis_ids=("analysis-1",),
        evidence_ids=(evidence_id,),
        proposed_changes=("clarify unavailable-source wording",),
    )
    weights = DynamicWeightProposal(
        proposal_id="weights-1",
        analysis_ids=("analysis-1",),
        weights=FrozenMapping(
            {
                "technical": Decimal("0.5"),
                "quantitative": Decimal("0.5"),
            }
        ),
        evidence_ids=(evidence_id,),
    )
    assert reflection.research_only is True
    assert reflection.production_prompt_mutation is False
    assert weights.research_only is True
    assert weights.production_weight_mutation is False
    assert reflection.promotion_status == weights.promotion_status == "REQUIRES_APPROVAL"
    disabled = AdvancedResearchProposalGate(
        AdvancedFeatureFlags(),
        evidence_registry,
    )
    with pytest.raises(ValueError, match="ADVANCED_REFLECTION_DISABLED"):
        disabled.reflection(reflection)
    with pytest.raises(ValueError, match="ADVANCED_DYNAMIC_WEIGHTS_DISABLED"):
        disabled.dynamic_weights(weights)
    enabled = AdvancedResearchProposalGate(
        AdvancedFeatureFlags(reflection=True, dynamic_weights=True),
        evidence_registry,
    )
    assert enabled.reflection(reflection) == reflection
    assert enabled.dynamic_weights(weights) == weights
    unsupported_scope = reflection.model_copy(
        update={"analysis_ids": ("analysis-1", "fabricated-analysis")}
    )
    with pytest.raises(ValueError, match="ADVANCED_PROPOSAL_ANALYSIS_SCOPE_UNSUPPORTED"):
        enabled.reflection(unsupported_scope)


def test_advanced_flags_and_trading_safety_default_off() -> None:
    assert AdvancedFeatureFlags.from_settings(settings) == AdvancedFeatureFlags()
    assert settings.FEATURE_ADVANCED_NEWS is False
    assert settings.FEATURE_ADVANCED_ONCHAIN is False
    assert settings.FEATURE_ADVANCED_MACRO is False
    assert settings.FEATURE_ADVANCED_SENTIMENT is False
    assert settings.FEATURE_ADVANCED_REGIME is False
    assert settings.FEATURE_ADVANCED_ETH is False
    assert settings.FEATURE_ADVANCED_REFLECTION is False
    assert settings.FEATURE_ADVANCED_DYNAMIC_WEIGHTS is False
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.PRIVATE_EXCHANGE_API_ENABLED is False


def test_source_semantic_ranges_fail_closed() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    onchain = _observation(AdvancedSourceKind.ONCHAIN, as_of)
    payload = onchain.model_dump()
    payload["values"]["metric_value"] = "-1"
    with pytest.raises(ValueError, match="ADVANCED_ONCHAIN_SCHEMA_INVALID"):
        AdvancedSourceObservation.model_validate(payload)

    macro = _observation(AdvancedSourceKind.MACRO, as_of)
    for series_id, unit, value in (
        ("CPI", "percent", "101"),
        ("FED_FUNDS", "percent", "-0.1"),
        ("DXY", "index", "0"),
    ):
        payload = macro.model_dump()
        payload["values"].update(
            {"series_id": series_id, "unit": unit, "value": value}
        )
        with pytest.raises(ValueError, match="ADVANCED_MACRO_SCHEMA_INVALID"):
            AdvancedSourceObservation.model_validate(payload)


@pytest.mark.asyncio
async def test_coordinator_emits_complete_research_only_agent_set() -> None:
    licenses = SourceLicenseRegistry()
    coordinator = AdvancedAgentCoordinator(
        AdvancedSourceService(
            flags=AdvancedFeatureFlags(),
            providers=FrozenMapping({}),
            evidence=AdvancedEvidenceRegistry(licenses),
            licenses=licenses,
        )
    )
    bundle = await coordinator.run(
        analysis_id="advanced-bundle",
        symbol="BTCUSDT",
        as_of_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert tuple(item.kind for item in bundle.assessments) == tuple(AdvancedSourceKind)
    assert all(
        item.reason_codes == ("ADVANCED_FEATURE_DISABLED",)
        for item in bundle.assessments
    )
    assert bundle.research_only is True
    assert bundle.production_authority is False
