import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import pytest

from packages.common.immutable import FrozenMapping
from packages.experiments.service import CanonicalPayload, ExperimentRecord
from packages.experiments.thesis_protocol import (
    EXPECTED_CONTRASTS,
    EXPECTED_VARIANTS,
    ResearchAblationDecisionFunction,
    ThesisExperimentIdentity,
    build_schedule,
    build_thesis_identities,
    canonical_json,
    load_protocol,
    observed_mean,
    partition_calendar_blocks,
    protocol_checksum,
    publish_no_clobber,
    validate_protocol,
)

ROOT = Path(__file__).resolve().parents[2]
THESIS = ROOT / "docs" / "thesis"
PROTOCOL_PATH = ROOT / "configs" / "research" / "thesis_protocol_v1.json"


def _base_experiment(
    *,
    symbol: str = "BTCUSDT",
    as_of: datetime = datetime(2026, 8, 1, tzinfo=timezone.utc),
) -> ExperimentRecord:
    raw = CanonicalPayload.capture({"close": "50000", "source": "binance_public"})
    normalized = CanonicalPayload.capture({"close": "50000"})
    features = CanonicalPayload.capture({"rsi_14": "55"})
    evidence = CanonicalPayload.capture({"evidence_ids": ["ev-1"]})
    models = FrozenMapping({"quantitative": "xgb-approved-v1"})
    prompts = FrozenMapping({"technical": "technical-v1"})
    experiment_id = ExperimentRecord.derive_id(
        analysis_id="paired-analysis-1",
        symbol=symbol,
        timeframe="4h",
        as_of_time=as_of,
        raw_checksum=raw.checksum,
        normalized_checksum=normalized.checksum,
        feature_checksum=features.checksum,
        evidence_checksum=evidence.checksum,
        model_versions=dict(models),
        prompt_versions=dict(prompts),
    )
    return ExperimentRecord(
        experiment_id=experiment_id,
        analysis_id="paired-analysis-1",
        sequence_number=1,
        symbol=symbol,
        timeframe="4h",
        as_of_time=as_of,
        recorded_at=as_of + timedelta(seconds=1),
        raw_inputs=raw,
        normalized_inputs=normalized,
        feature_snapshot=features,
        evidence_snapshot=evidence,
        model_versions=models,
        prompt_versions=prompts,
        agent_outputs=CanonicalPayload.capture({"status": "PENDING"}),
        debate_transcript=CanonicalPayload.capture({"status": "PENDING"}),
        verification_result=CanonicalPayload.capture({"status": "PENDING"}),
        risk_result=CanonicalPayload.capture({"status": "PENDING"}),
        manager_result=CanonicalPayload.capture({"status": "PENDING"}),
        verification_rejected=False,
        expected_field_count=10,
        missing_field_count=0,
        data_quality=CanonicalPayload.capture({"status": "HEALTHY"}),
    )


def test_thesis_package_has_required_structure() -> None:
    overview = (THESIS / "README.md").read_text()
    for heading in (
        "## Problem statement",
        "## Research questions",
        "## Related architecture",
        "## Methodology",
        "## Dataset",
        "## Baselines",
        "## Experiments and ablations",
        "## Results",
        "## Error analysis",
        "## Limitations",
        "## Ethics and safety",
        "## Reproducibility",
        "## Future work",
    ):
        assert heading in overview

    for filename in (
        "METHODOLOGY.md",
        "EXPERIMENT_PROTOCOL.md",
        "DATA_DICTIONARY.md",
        "REPRODUCIBILITY.md",
        "RESULTS_STATUS.md",
    ):
        assert (THESIS / filename).is_file()


def test_required_experiments_are_explicitly_pending_evidence() -> None:
    results = (THESIS / "RESULTS_STATUS.md").read_text()
    table_rows = [
        line
        for line in results.splitlines()
        if line.startswith("| ") and not line.startswith("|---") and "Result status" not in line
    ]
    rows = [line for line in table_rows if "| `PENDING_EVIDENCE` |" in line]
    assert table_rows == rows
    assert len(rows) == 10
    for experiment in (
        "Quantitative-only",
        "Single-Agent",
        "Multi-Agent without debate",
        "Multi-Agent with debate",
        "Without Verification",
        "With Verification",
        "Without derivatives",
        "With derivatives",
        "Static weights",
        "Dynamic weights research-only",
    ):
        assert any(f"| {experiment} |" in row for row in rows)


def test_thesis_package_preserves_safety_and_honest_result_labels() -> None:
    package = "\n".join(path.read_text() for path in sorted(THESIS.glob("*.md")))
    assert "live execution system" in package
    assert "No observed sample size is claimed" in package
    assert "p-value, or significance result" in package
    assert "Paper PnL and return are simulated" in package
    assert "Dynamic weights are proposals only" in package
    assert "PENDING_EVIDENCE" in package


def test_frozen_protocol_is_exact_and_builds_deterministic_schedule(tmp_path: Path) -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    assert protocol_checksum(protocol) == (
        "38353eb3676433b05d1102006daf398a4d676a94de945ec2fdc9e41bde55fc90"
    )
    assert {row["variant_id"] for row in protocol["variants"]} == EXPECTED_VARIANTS
    assert {row["contrast_id"] for row in protocol["contrasts"]} == EXPECTED_CONTRASTS
    assert len(protocol["folds"]) == 6
    assert protocol["analysis"]["primary_endpoint"]["population"].startswith(
        "all scheduled attempts"
    )
    assert protocol["analysis"]["stopping_rule"].startswith("no efficacy stopping")
    assert protocol["result_policy"]["initial_status"] == "PENDING_EVIDENCE"
    assert protocol["result_policy"]["live_claim_allowed"] is False
    assert protocol["result_policy"]["promotion_allowed"] is False
    assert protocol["execution_readiness"]["collection_may_start"] is False

    schedule = build_schedule(protocol)
    assert schedule["scheduled_clock_count"] == 2190
    assert schedule["variant_count"] == 10
    assert schedule["planned_attempt_count"] == 21900
    assert schedule["clocks"][0] == "2026-08-01T00:00:00+00:00"
    assert schedule["clocks"][-1] == "2027-07-31T20:00:00+00:00"

    output = tmp_path / "schedule.json"
    publish_no_clobber(output, schedule)
    assert json.loads(output.read_text()) == schedule
    with pytest.raises(FileExistsError):
        publish_no_clobber(output, schedule)
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("components", {}),
        lambda value: value.__setitem__("temporal_policy", {}),
        lambda value: value["scope"].__setitem__("decision_minutes", [17]),
        lambda value: value["analysis"]["primary_endpoint"].__setitem__(
            "formula", "choose after outcomes"
        ),
        lambda value: value["contrasts"][0].__setitem__(
            "changed_component", "anything"
        ),
    ],
)
def test_protocol_v1_rejects_any_mutated_copy(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text())
    changed = copy.deepcopy(protocol)
    mutation(changed)
    with pytest.raises(ValueError, match="THESIS_PROTOCOL_V1_DIGEST_MISMATCH"):
        validate_protocol(changed)


def test_direct_schedule_api_rejects_mutated_protocol() -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text())
    protocol["scope"]["decision_minutes"] = [17]
    with pytest.raises(ValueError, match="THESIS_PROTOCOL_V1_DIGEST_MISMATCH"):
        build_schedule(protocol)


def test_schedule_publication_cleans_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    output = tmp_path / "schedule.json"

    def fail_link(_source: Path, _target: Path) -> None:
        raise OSError("simulated atomic-install failure")

    monkeypatch.setattr(
        "packages.experiments.thesis_protocol.os.link",
        fail_link,
    )
    with pytest.raises(OSError, match="simulated atomic-install failure"):
        publish_no_clobber(output, build_schedule(protocol))
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_thesis_identity_is_unique_for_all_ten_variants() -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    base = _base_experiment()
    identities = build_thesis_identities(
        protocol,
        base_record=base,
    )
    assert len(identities) == 10
    assert len({identity.thesis_experiment_id for identity in identities}) == 10
    assert len({identity.variant_config_sha256 for identity in identities}) == 10
    assert {identity.variant_id for identity in identities} == EXPECTED_VARIANTS
    assert all(
        identity.schema_version == "thesis_experiment_identity_v1"
        and identity.protocol_sha256
        == "38353eb3676433b05d1102006daf398a4d676a94de945ec2fdc9e41bde55fc90"
        for identity in identities
    )
    first = identities[0]
    first.validate_binding(protocol, base)
    tampered = first.model_dump()
    tampered["variant_id"] = "single_agent"
    with pytest.raises(ValueError, match="THESIS_EXPERIMENT_IDENTITY_MISMATCH"):
        ThesisExperimentIdentity.model_validate(tampered)
    with pytest.raises(
        ValueError,
        match="THESIS_EXPERIMENT_IDENTITY_SCOPE_INVALID",
    ):
        build_thesis_identities(
            protocol,
            base_record=_base_experiment(symbol="ETHUSDT"),
        )
    late = base.model_copy(
        update={"recorded_at": base.as_of_time + timedelta(hours=4)}
    )
    with pytest.raises(
        ValueError,
        match="THESIS_EXPERIMENT_IDENTITY_SCOPE_INVALID",
    ):
        build_thesis_identities(protocol, base_record=late)
    forged = first.model_dump()
    forged["base_record_checksum"] = "f" * 64
    forged["thesis_experiment_id"] = ThesisExperimentIdentity.derive_id(
        base_experiment_id=forged["base_experiment_id"],
        base_record_checksum=forged["base_record_checksum"],
        protocol_sha256=forged["protocol_sha256"],
        variant_id=forged["variant_id"],
        variant_config_sha256=forged["variant_config_sha256"],
        cohort_id=forged["cohort_id"],
        paired_analysis_id=forged["paired_analysis_id"],
        as_of_time=forged["as_of_time"],
        symbol=forged["symbol"],
        timeframe=forged["timeframe"],
        horizon=forged["horizon"],
    )
    forged_identity = ThesisExperimentIdentity.model_validate(forged)
    with pytest.raises(ValueError, match="THESIS_PROTOCOL_BINDING_MISMATCH"):
        forged_identity.validate_binding(protocol, base)
    for updates in (
        {"protocol_sha256": "0" * 64},
        {
            "variant_id": "not_declared",
            "variant_config_sha256": "1" * 64,
        },
        {"horizon": "99d"},
        {"cohort_id": "2" * 64},
    ):
        forged = first.model_dump()
        forged.update(updates)
        forged["thesis_experiment_id"] = ThesisExperimentIdentity.derive_id(
            base_experiment_id=forged["base_experiment_id"],
            base_record_checksum=forged["base_record_checksum"],
            protocol_sha256=forged["protocol_sha256"],
            variant_id=forged["variant_id"],
            variant_config_sha256=forged["variant_config_sha256"],
            cohort_id=forged["cohort_id"],
            paired_analysis_id=forged["paired_analysis_id"],
            as_of_time=forged["as_of_time"],
            symbol=forged["symbol"],
            timeframe=forged["timeframe"],
            horizon=forged["horizon"],
        )
        forged_identity = ThesisExperimentIdentity.model_validate(forged)
        with pytest.raises(ValueError, match="THESIS_PROTOCOL_BINDING_MISMATCH"):
            forged_identity.validate_binding(protocol, base)
    bypassed_record = base.model_copy(
        update={"experiment_id": "exp_" + "0" * 64}
    )
    with pytest.raises(ValueError, match="EXPERIMENT_ID_MISMATCH"):
        first.validate_binding(protocol, bypassed_record)
    off_grid = _base_experiment(
        as_of=datetime(2026, 8, 1, 1, tzinfo=timezone.utc)
    )
    forged = first.model_dump()
    forged.update(
        {
            "base_experiment_id": off_grid.experiment_id,
            "base_record_checksum": hashlib.sha256(
                canonical_json(off_grid.model_dump(mode="json"))
            ).hexdigest(),
            "paired_analysis_id": off_grid.analysis_id,
            "as_of_time": off_grid.as_of_time,
        }
    )
    forged["thesis_experiment_id"] = ThesisExperimentIdentity.derive_id(
        base_experiment_id=forged["base_experiment_id"],
        base_record_checksum=forged["base_record_checksum"],
        protocol_sha256=forged["protocol_sha256"],
        variant_id=forged["variant_id"],
        variant_config_sha256=forged["variant_config_sha256"],
        cohort_id=forged["cohort_id"],
        paired_analysis_id=forged["paired_analysis_id"],
        as_of_time=forged["as_of_time"],
        symbol=forged["symbol"],
        timeframe=forged["timeframe"],
        horizon=forged["horizon"],
    )
    off_grid_identity = ThesisExperimentIdentity.model_validate(forged)
    with pytest.raises(ValueError, match="THESIS_PROTOCOL_BINDING_MISMATCH"):
        off_grid_identity.validate_binding(protocol, off_grid)


def test_contrasts_change_only_declared_research_function_fields() -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    variants = {row["variant_id"]: row for row in protocol["variants"]}
    for contrast in protocol["contrasts"]:
        control = variants[contrast["control"]]
        treatment = variants[contrast["treatment"]]
        differing = {
            key
            for key in set(control) | set(treatment)
            if key not in {"variant_id"} and control.get(key) != treatment.get(key)
        }
        assert differing == set(contrast["changed_fields"])


def test_one_research_decision_function_is_used_across_contrasts() -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    all_scores = {
        "technical_agent": Decimal("1"),
        "derivatives_agent": Decimal("-1"),
        "quantitative_agent": Decimal("1"),
    }
    no_debate = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="multi_no_debate",
        component_scores=all_scores,
        debate_score=None,
        verification_passed=True,
    )
    with_debate = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="multi_with_debate",
        component_scores=all_scores,
        debate_score=Decimal("-1"),
        verification_passed=True,
    )
    assert (no_debate, with_debate) == ("BUY", "HOLD")

    without_verification = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="without_verification",
        component_scores=all_scores,
        debate_score=Decimal("1"),
        verification_passed=False,
    )
    with_verification = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="with_verification",
        component_scores=all_scores,
        debate_score=Decimal("1"),
        verification_passed=False,
    )
    assert (without_verification, with_verification) == ("BUY", "REJECTED")

    weighting_scores = {
        "technical_agent": Decimal("1"),
        "derivatives_agent": Decimal("-1"),
        "quantitative_agent": Decimal("1"),
    }
    static = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="static_weights",
        component_scores=weighting_scores,
        debate_score=Decimal("0"),
        verification_passed=True,
    )
    dynamic = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="dynamic_weights_research_only",
        component_scores=weighting_scores,
        debate_score=Decimal("0"),
        verification_passed=True,
        dynamic_weights={
            "technical_agent": Decimal("0.1"),
            "derivatives_agent": Decimal("0.8"),
            "quantitative_agent": Decimal("0.1"),
        },
    )
    assert (static, dynamic) == ("BUY", "HOLD")
    invalid_dynamic = ResearchAblationDecisionFunction.decide(
        protocol,
        variant_id="dynamic_weights_research_only",
        component_scores=weighting_scores,
        debate_score=Decimal("0"),
        verification_passed=True,
        dynamic_weights={
            "technical_agent": Decimal("NaN"),
            "derivatives_agent": Decimal("0"),
            "quantitative_agent": Decimal("1"),
        },
    )
    assert invalid_dynamic == "UNAVAILABLE"


def test_calendar_blocks_preserve_missing_clock_slots() -> None:
    values: list[Decimal | None] = [Decimal(index) for index in range(45)]
    values[1] = None
    values[42] = None
    blocks = partition_calendar_blocks(values)
    assert tuple(len(block) for block in blocks) == (42, 3)
    assert blocks[0][1] is None
    assert blocks[1][0] is None
    assert observed_mean(values) == sum(
        (value for value in values if value is not None),
        Decimal("0"),
    ) / Decimal(43)


def test_all_relative_markdown_links_resolve() -> None:
    unresolved: list[str] = []
    for document in sorted(THESIS.glob("*.md")):
        for target in re.findall(r"\[[^]]+]\(([^)]+)\)", document.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            path = (document.parent / target).resolve()
            if not path.exists():
                unresolved.append(f"{document.name}:{target}")
    assert unresolved == []
