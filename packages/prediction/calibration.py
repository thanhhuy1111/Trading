"""Pure calibration-quality metrics for a binary probability stream.

Used offline (training/evaluation) to compute the `calibration_score` recorded on a
`ModelArtifact`, and available to `evaluation.py` / future shadow-mode monitoring. No
side effects, no I/O.
"""

from typing import List, Sequence, TypedDict


class ReliabilityBucket(TypedDict):
    bucket_lower: float
    bucket_upper: float
    count: int
    mean_predicted: float
    empirical_frequency: float


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")
    if not probabilities:
        raise ValueError("cannot score an empty sample")
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)) / len(probabilities)


def reliability_buckets(
    probabilities: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> List[ReliabilityBucket]:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")

    buckets: List[ReliabilityBucket] = []
    for i in range(n_bins):
        lower = i / n_bins
        upper = (i + 1) / n_bins
        in_bucket = [
            (p, y)
            for p, y in zip(probabilities, outcomes, strict=True)
            if (lower <= p < upper) or (i == n_bins - 1 and p == upper)
        ]
        if not in_bucket:
            buckets.append(
                ReliabilityBucket(
                    bucket_lower=lower, bucket_upper=upper, count=0, mean_predicted=0.0, empirical_frequency=0.0
                )
            )
            continue
        mean_pred = sum(p for p, _ in in_bucket) / len(in_bucket)
        freq = sum(y for _, y in in_bucket) / len(in_bucket)
        buckets.append(
            ReliabilityBucket(
                bucket_lower=lower,
                bucket_upper=upper,
                count=len(in_bucket),
                mean_predicted=mean_pred,
                empirical_frequency=freq,
            )
        )
    return buckets


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> float:
    total = len(probabilities)
    if total == 0:
        raise ValueError("cannot score an empty sample")
    buckets = reliability_buckets(probabilities, outcomes, n_bins)
    return sum(b["count"] / total * abs(b["mean_predicted"] - b["empirical_frequency"]) for b in buckets)


def calibration_score_from_ece(ece: float) -> float:
    """Maps expected calibration error (lower is better, [0, 1]) onto a [0, 1] score
    (higher is better) so it can be compared directly against
    RecommendationConfig.min_calibration_score.
    """
    return max(0.0, 1.0 - ece)
