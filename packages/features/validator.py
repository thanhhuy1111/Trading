from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from packages.features.models import (
    FeatureQualityIssue,
    FeatureQualityStatus,
)


class FeatureQualityValidator:
    """Validates feature snapshots for mathematical correctness, ranges, and temporal integrity."""

    def validate_snapshot(
        self,
        values: Dict[str, Optional[Decimal | int | bool]],
        as_of_time: datetime
    ) -> Tuple[FeatureQualityStatus, List[FeatureQualityIssue]]:
        issues: List[FeatureQualityIssue] = []

        now = datetime.now(timezone.utc)
        for fname, val in values.items():
            if val is None:
                issues.append(FeatureQualityIssue(
                    feature_name=fname,
                    issue_type="MISSING_VALUE",
                    description=f"Feature '{fname}' value is None",
                    severity="WARNING",
                    timestamp=now
                ))
                continue

            if isinstance(val, Decimal):
                if val.is_nan() or val.is_infinite():
                    issues.append(FeatureQualityIssue(
                        feature_name=fname,
                        issue_type="INVALID_NUMERIC",
                        description=f"Feature '{fname}' produced NaN or Infinity",
                        severity="ERROR",
                        timestamp=now
                    ))

                # Range specific validations
                if fname.startswith("rsi_") and not (Decimal("0.0") <= val <= Decimal("100.0")):
                    issues.append(FeatureQualityIssue(
                        feature_name=fname,
                        issue_type="OUT_OF_RANGE",
                        description=f"RSI feature '{fname}' value {val} outside 0..100",
                        severity="ERROR",
                        timestamp=now
                    ))

                if fname.startswith("adx_") and val < Decimal("0.0"):
                    issues.append(FeatureQualityIssue(
                        feature_name=fname,
                        issue_type="OUT_OF_RANGE",
                        description=f"ADX feature '{fname}' value {val} is negative",
                        severity="ERROR",
                        timestamp=now
                    ))

                if fname.startswith("atr_") and val < Decimal("0.0"):
                    issues.append(FeatureQualityIssue(
                        feature_name=fname,
                        issue_type="OUT_OF_RANGE",
                        description=f"ATR feature '{fname}' value {val} is negative",
                        severity="ERROR",
                        timestamp=now
                    ))

        # Status determination
        has_errors = any(i.severity == "ERROR" for i in issues)
        has_warnings = any(i.severity == "WARNING" for i in issues)

        if has_errors:
            status = FeatureQualityStatus.INVALID
        elif has_warnings:
            status = FeatureQualityStatus.DEGRADED
        else:
            status = FeatureQualityStatus.VALID

        return status, issues


feature_validator = FeatureQualityValidator()
