"""Validate and materialize the frozen Phase 15 thesis protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.experiments.service import ExperimentRecord

EXPECTED_VARIANTS = {
    "quantitative_only",
    "single_agent",
    "multi_no_debate",
    "multi_with_debate",
    "without_verification",
    "with_verification",
    "without_derivatives",
    "with_derivatives",
    "static_weights",
    "dynamic_weights_research_only",
}
EXPECTED_CONTRASTS = {
    "C1_AGENT_INCREMENT",
    "C2_DEBATE_INCREMENT",
    "C3_VERIFICATION_INCREMENT",
    "C4_DERIVATIVES_INCREMENT",
    "C5_DYNAMIC_WEIGHT_INCREMENT",
}
EXPECTED_PROTOCOL_SHA256 = "38353eb3676433b05d1102006daf398a4d676a94de945ec2fdc9e41bde55fc90"


class ThesisExperimentIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(pattern=r"^thesis_experiment_identity_v1$")
    thesis_experiment_id: str = Field(pattern=r"^thexp_[0-9a-f]{64}$")
    base_experiment_id: str = Field(pattern=r"^exp_[0-9a-f]{64}$")
    base_record_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_id: str
    variant_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cohort_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    paired_analysis_id: str
    as_of_time: datetime
    symbol: str
    timeframe: str
    horizon: str

    @model_validator(mode="after")
    def validate_identity(self) -> "ThesisExperimentIdentity":
        if self.as_of_time.utcoffset() != timedelta(0):
            raise ValueError("THESIS_EXPERIMENT_IDENTITY_TIME_INVALID")
        expected = self.derive_id(
            base_experiment_id=self.base_experiment_id,
            base_record_checksum=self.base_record_checksum,
            protocol_sha256=self.protocol_sha256,
            variant_id=self.variant_id,
            variant_config_sha256=self.variant_config_sha256,
            cohort_id=self.cohort_id,
            paired_analysis_id=self.paired_analysis_id,
            as_of_time=self.as_of_time,
            symbol=self.symbol,
            timeframe=self.timeframe,
            horizon=self.horizon,
        )
        if self.thesis_experiment_id != expected:
            raise ValueError("THESIS_EXPERIMENT_IDENTITY_MISMATCH")
        return self

    @staticmethod
    def derive_id(
        *,
        base_experiment_id: str,
        base_record_checksum: str,
        protocol_sha256: str,
        variant_id: str,
        variant_config_sha256: str,
        cohort_id: str,
        paired_analysis_id: str,
        as_of_time: datetime,
        symbol: str,
        timeframe: str,
        horizon: str,
    ) -> str:
        return "thexp_" + hashlib.sha256(
            canonical_json(
                {
                    "base_experiment_id": base_experiment_id,
                    "base_record_checksum": base_record_checksum,
                    "protocol_sha256": protocol_sha256,
                    "variant_id": variant_id,
                    "variant_config_sha256": variant_config_sha256,
                    "cohort_id": cohort_id,
                    "paired_analysis_id": paired_analysis_id,
                    "as_of_time": as_of_time.isoformat(),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "horizon": horizon,
                }
            )
        ).hexdigest()

    def validate_binding(
        self,
        protocol: dict[str, Any],
        record: ExperimentRecord,
    ) -> None:
        validate_protocol(protocol)
        record = ExperimentRecord.model_validate(record.model_dump())
        checksum = hashlib.sha256(
            canonical_json(record.model_dump(mode="json"))
        ).hexdigest()
        scope = protocol["scope"]
        start = _parse_utc(scope["collection_start"])
        end = _parse_utc(scope["collection_end_exclusive"])
        variant = next(
            (
                candidate
                for candidate in protocol["variants"]
                if candidate["variant_id"] == self.variant_id
            ),
            None,
        )
        if variant is None:
            raise ValueError("THESIS_PROTOCOL_BINDING_MISMATCH")
        fold_id = next(
            (
                fold["fold_id"]
                for fold in protocol["folds"]
                if _parse_utc(fold["start"])
                <= record.as_of_time
                < _parse_utc(fold["end_exclusive"])
            ),
            None,
        )
        if fold_id is None:
            raise ValueError("THESIS_PROTOCOL_BINDING_MISMATCH")
        expected_cohort_id = _derive_cohort_id(protocol, fold_id)
        if (
            record.experiment_id != self.base_experiment_id
            or checksum != self.base_record_checksum
            or record.analysis_id != self.paired_analysis_id
            or record.symbol != self.symbol
            or record.timeframe != self.timeframe
            or record.as_of_time != self.as_of_time
            or record.as_of_time < start
            or record.as_of_time >= end
            or (record.as_of_time - start)
            % timedelta(hours=scope["decision_cadence_hours"])
            != timedelta(0)
            or self.protocol_sha256 != protocol_checksum(protocol)
            or self.variant_config_sha256
            != hashlib.sha256(canonical_json(variant)).hexdigest()
            or self.cohort_id != expected_cohort_id
            or self.symbol != scope["symbol"]
            or self.timeframe != scope["timeframe"]
            or self.horizon != scope["outcome_horizons"][0]
            or record.recorded_at
            >= self.as_of_time
            + timedelta(hours=scope["decision_cadence_hours"])
        ):
            raise ValueError("THESIS_PROTOCOL_BINDING_MISMATCH")


class ResearchAblationDecisionFunction:
    """One no-action decision function shared by every thesis contrast arm."""

    version = "1.0.0"

    @staticmethod
    def decide(
        protocol: dict[str, Any],
        *,
        variant_id: str,
        component_scores: dict[str, Decimal],
        debate_score: Decimal | None,
        verification_passed: bool,
        dynamic_weights: dict[str, Decimal] | None = None,
    ) -> str:
        validate_protocol(protocol)
        variant = next(
            (
                candidate
                for candidate in protocol["variants"]
                if candidate["variant_id"] == variant_id
            ),
            None,
        )
        if variant is None:
            raise ValueError("THESIS_VARIANT_UNKNOWN")
        required = (
            ("quantitative_agent",)
            if variant_id == "quantitative_only"
            else ("quantitative_agent", "technical_agent")
            if variant_id == "single_agent"
            else tuple(variant["agents"])
        )
        if set(component_scores) != set(required) or any(
            not score.is_finite() or score not in {-1, 0, 1}
            for score in component_scores.values()
        ):
            return "UNAVAILABLE"
        components = protocol["components"]
        if variant["weighting"] == "QUANTITATIVE_ONLY":
            weights = components["quantitative_only_weights"]
        elif variant["weighting"] == "SINGLE_PLUS_QUANTITATIVE_BASE":
            weights = components["single_agent_weights"]
        elif variant["weighting"] == "STATIC_RENORMALIZED_EQUAL":
            weights = components["static_without_derivatives_weights"]
        elif variant["weighting"] == "DYNAMIC_RESEARCH_ONLY":
            if dynamic_weights is None:
                return "UNAVAILABLE"
            weights = dynamic_weights
        else:
            weights = components["static_weights"]
        decimal_weights = {
            name: Decimal(str(value)) for name, value in weights.items()
        }
        if (
            set(decimal_weights) != set(required)
            or any(
                not value.is_finite() or value < 0
                for value in decimal_weights.values()
            )
            or sum(decimal_weights.values(), Decimal("0")) != Decimal("1")
        ):
            return "UNAVAILABLE"
        score = sum(
            (
                decimal_weights[name] * component_scores[name]
                for name in required
            ),
            Decimal("0"),
        )
        if variant["debate"]:
            if (
                debate_score is None
                or not debate_score.is_finite()
                or debate_score not in {-1, 0, 1}
            ):
                return "UNAVAILABLE"
            score = (score + debate_score) / Decimal("2")
        elif debate_score is not None:
            raise ValueError("THESIS_DEBATE_SCORE_UNEXPECTED")
        if variant["verification"] and not verification_passed:
            return "REJECTED"
        return "BUY" if score > 0 else "HOLD"


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def load_protocol(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("THESIS_PROTOCOL_NOT_OBJECT")
    validate_protocol(raw)
    return raw


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("THESIS_PROTOCOL_TIME_NOT_UTC")
    return parsed


def _derive_cohort_id(protocol: dict[str, Any], fold_id: str) -> str:
    scope = protocol["scope"]
    return hashlib.sha256(
        canonical_json(
            {
                "protocol_sha256": protocol_checksum(protocol),
                "fold_id": fold_id,
                "symbol": scope["symbol"],
                "timeframe": scope["timeframe"],
                "horizon": scope["outcome_horizons"][0],
            }
        )
    ).hexdigest()


def validate_protocol(protocol: dict[str, Any]) -> None:
    if protocol.get("schema_version") != "thesis_protocol_v1":
        raise ValueError("THESIS_PROTOCOL_SCHEMA_INVALID")
    scope = protocol["scope"]
    if (
        scope["symbol"] != "BTCUSDT"
        or scope["timeframe"] != "4h"
        or scope["timezone"] != "UTC"
        or scope["decision_cadence_hours"] != 4
        or scope["outcome_horizons"] != ["4h"]
    ):
        raise ValueError("THESIS_PROTOCOL_SCOPE_INVALID")
    start = _parse_utc(scope["collection_start"])
    end = _parse_utc(scope["collection_end_exclusive"])
    if start >= end:
        raise ValueError("THESIS_PROTOCOL_WINDOW_INVALID")

    folds = protocol["folds"]
    if len(folds) != 6:
        raise ValueError("THESIS_PROTOCOL_FOLDS_INVALID")
    cursor = start
    for fold in folds:
        fold_start = _parse_utc(fold["start"])
        fold_end = _parse_utc(fold["end_exclusive"])
        if fold_start != cursor or fold_start >= fold_end:
            raise ValueError("THESIS_PROTOCOL_FOLDS_INVALID")
        cursor = fold_end
    if cursor != end:
        raise ValueError("THESIS_PROTOCOL_FOLDS_INVALID")

    variants = protocol["variants"]
    variant_ids = [variant["variant_id"] for variant in variants]
    if len(variant_ids) != len(set(variant_ids)) or set(variant_ids) != EXPECTED_VARIANTS:
        raise ValueError("THESIS_PROTOCOL_VARIANTS_INVALID")
    if any(variant["authority"] not in {"RESEARCH_ONLY", "RESEARCH_ONLY_NO_ACTION"} for variant in variants):
        raise ValueError("THESIS_PROTOCOL_AUTHORITY_INVALID")

    contrasts = protocol["contrasts"]
    contrast_ids = [contrast["contrast_id"] for contrast in contrasts]
    if len(contrast_ids) != len(set(contrast_ids)) or set(contrast_ids) != EXPECTED_CONTRASTS:
        raise ValueError("THESIS_PROTOCOL_CONTRASTS_INVALID")
    for contrast in contrasts:
        if contrast["control"] not in EXPECTED_VARIANTS or contrast["treatment"] not in EXPECTED_VARIANTS:
            raise ValueError("THESIS_PROTOCOL_CONTRASTS_INVALID")

    analysis = protocol["analysis"]
    required_analysis = {
        "primary_endpoint",
        "secondary_endpoints",
        "missing_policy",
        "sensitivity",
        "dependence",
        "inference",
        "information_target",
        "minimum_completeness",
        "stopping_rule",
    }
    if set(analysis) != required_analysis:
        raise ValueError("THESIS_PROTOCOL_ANALYSIS_INVALID")
    if protocol["result_policy"] != {
        "initial_status": "PENDING_EVIDENCE",
        "paper_label": "SIMULATED_PAPER_ONLY",
        "live_claim_allowed": False,
        "promotion_allowed": False,
    }:
        raise ValueError("THESIS_PROTOCOL_RESULT_POLICY_INVALID")
    if protocol_checksum(protocol) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("THESIS_PROTOCOL_V1_DIGEST_MISMATCH")


def protocol_checksum(protocol: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(protocol)).hexdigest()


def build_schedule(protocol: dict[str, Any]) -> dict[str, Any]:
    validate_protocol(protocol)
    scope = protocol["scope"]
    current = _parse_utc(scope["collection_start"])
    end = _parse_utc(scope["collection_end_exclusive"])
    step = timedelta(hours=scope["decision_cadence_hours"])
    clocks: list[str] = []
    while current < end:
        clocks.append(current.isoformat())
        current += step
    return {
        "schema_version": "thesis_schedule_v1",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_checksum(protocol),
        "result_status": "PENDING_EVIDENCE",
        "scheduled_clock_count": len(clocks),
        "variant_count": len(protocol["variants"]),
        "planned_attempt_count": len(clocks) * len(protocol["variants"]),
        "clocks": clocks,
    }


def build_thesis_identities(
    protocol: dict[str, Any],
    *,
    base_record: ExperimentRecord,
) -> tuple[ThesisExperimentIdentity, ...]:
    validate_protocol(protocol)
    base_record = ExperimentRecord.model_validate(base_record.model_dump())
    scope = protocol["scope"]
    start = _parse_utc(scope["collection_start"])
    end = _parse_utc(scope["collection_end_exclusive"])
    if (
        base_record.symbol != scope["symbol"]
        or base_record.timeframe != scope["timeframe"]
        or base_record.as_of_time.utcoffset() != timedelta(0)
        or base_record.as_of_time < start
        or base_record.as_of_time >= end
        or base_record.recorded_at >= base_record.as_of_time + timedelta(hours=4)
        or (base_record.as_of_time - start)
        % timedelta(hours=scope["decision_cadence_hours"])
        != timedelta(0)
    ):
        raise ValueError("THESIS_EXPERIMENT_IDENTITY_SCOPE_INVALID")
    as_of_time = base_record.as_of_time
    fold_id = next(
        (
            fold["fold_id"]
            for fold in protocol["folds"]
            if _parse_utc(fold["start"])
            <= as_of_time
            < _parse_utc(fold["end_exclusive"])
        ),
        None,
    )
    if fold_id is None:
        raise ValueError("THESIS_EXPERIMENT_IDENTITY_FOLD_INVALID")
    digest = protocol_checksum(protocol)
    cohort_id = _derive_cohort_id(protocol, fold_id)
    base_record_checksum = hashlib.sha256(
        canonical_json(base_record.model_dump(mode="json"))
    ).hexdigest()
    identities: list[ThesisExperimentIdentity] = []
    for variant in protocol["variants"]:
        variant_sha256 = hashlib.sha256(canonical_json(variant)).hexdigest()
        thesis_experiment_id = ThesisExperimentIdentity.derive_id(
            base_experiment_id=base_record.experiment_id,
            base_record_checksum=base_record_checksum,
            protocol_sha256=digest,
            variant_id=variant["variant_id"],
            variant_config_sha256=variant_sha256,
            cohort_id=cohort_id,
            paired_analysis_id=base_record.analysis_id,
            as_of_time=as_of_time,
            symbol=scope["symbol"],
            timeframe=scope["timeframe"],
            horizon=scope["outcome_horizons"][0],
        )
        identity = ThesisExperimentIdentity(
            schema_version="thesis_experiment_identity_v1",
            thesis_experiment_id=thesis_experiment_id,
            base_experiment_id=base_record.experiment_id,
            base_record_checksum=base_record_checksum,
            protocol_sha256=digest,
            variant_id=variant["variant_id"],
            variant_config_sha256=variant_sha256,
            cohort_id=cohort_id,
            paired_analysis_id=base_record.analysis_id,
            as_of_time=as_of_time,
            symbol=scope["symbol"],
            timeframe=scope["timeframe"],
            horizon=scope["outcome_horizons"][0],
        )
        identity.validate_binding(protocol, base_record)
        identities.append(identity)
    return tuple(identities)


def partition_calendar_blocks(
    paired_differences: Sequence[Decimal | None],
    *,
    block_length: int = 42,
) -> tuple[tuple[Decimal | None, ...], ...]:
    if block_length <= 0:
        raise ValueError("THESIS_BLOCK_LENGTH_INVALID")
    return tuple(
        tuple(paired_differences[index : index + block_length])
        for index in range(0, len(paired_differences), block_length)
    )


def observed_mean(paired_differences: Sequence[Decimal | None]) -> Decimal | None:
    observed = tuple(value for value in paired_differences if value is not None)
    if not observed:
        return None
    return sum(observed, Decimal("0")) / Decimal(len(observed))


def publish_no_clobber(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "schedule"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--protocol", type=Path, required=True)
        if command == "schedule":
            subparser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = load_protocol(args.protocol)
    if args.command == "validate":
        print(protocol_checksum(protocol))
        return
    schedule = build_schedule(protocol)
    publish_no_clobber(args.output, schedule)
    print(schedule["protocol_sha256"])


if __name__ == "__main__":
    main()
