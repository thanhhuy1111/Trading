"""Multiple-testing / overfitting controls.

`ExperimentTracker` records every model/hyperparameter/feature-set/threshold combination
actually evaluated during a research session, so `experiments_tried` on an
`EvaluationReport` (packages.research.evaluation) is a real count, not a guess -- and so
the deflated Sharpe ratio below is computed against the true number of trials, not
whatever number happens to be convenient.

Deflated Sharpe Ratio (DSR) follows Bailey & Lopez de Prado (2014): it answers "what is
the probability the observed Sharpe ratio is genuinely positive, after accounting for
having tried N trials and for the return distribution's skew/kurtosis?" -- NOT "is this
Sharpe ratio big."

Probability of Backtest Overfitting (PBO) uses combinatorially symmetric cross-validation
(CSCV, Bailey et al. 2015) over a trials x partitions performance matrix (here: each
trial's per walk-forward-fold Sharpe/return, i.e. exactly the "window" breakdowns
`packages.research.evaluation.run_walk_forward_evaluation` already produces) -- it is the
fraction of IS/OOS splits in which the best in-sample trial performs BELOW the OOS median,
i.e. how often "the winner" was actually overfit to its in-sample slice.

Both are implemented for real (not stubbed), but both are also small-sample statistics --
with only 3-5 walk-forward folds and a handful of trials, treat the numeric values as
directional warnings, not precise probabilities. See docs/ALPHA_EVIDENCE_POLICY.md.
"""

import math
from datetime import datetime, timezone
from itertools import combinations
from typing import Dict, List, Optional
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, Field

from packages.research.exceptions import InsufficientDataError

_EULER_MASCHERONI = 0.5772156649015329


class ExperimentRecord(BaseModel):
    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str  # "model" | "hyperparameters" | "feature_set" | "threshold"
    description: str
    config_hash: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExperimentTracker:
    def __init__(self) -> None:
        self._records: List[ExperimentRecord] = []

    def record(self, kind: str, description: str, config_hash: str) -> ExperimentRecord:
        record = ExperimentRecord(kind=kind, description=description, config_hash=config_hash)
        self._records.append(record)
        return record

    @property
    def total_trials(self) -> int:
        return len(self._records)

    def count_by_kind(self, kind: str) -> int:
        return sum(1 for r in self._records if r.kind == kind)

    def all_records(self) -> List[ExperimentRecord]:
        return list(self._records)


def _expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    from scipy import stats

    if n_trials <= 1:
        return 0.0
    z1 = stats.norm.ppf(1 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
    return sharpe_std * ((1 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    trial_sharpe_std: Optional[float] = None,
) -> float:
    """Returns P(true Sharpe > 0 | observed_sharpe, n_trials, ...) in [0, 1].

    `trial_sharpe_std`: the standard deviation of Sharpe ratios ACROSS the trials actually
    run. When not supplied (e.g. only the winning trial's stats were retained), this
    defaults to 1.0 -- a standard, documented simplification (Bailey & Lopez de Prado use
    this when the full trial distribution isn't tracked); pass the real value when
    `ExperimentTracker` has it for a tighter estimate.
    """
    from scipy import stats

    if n_observations <= 1:
        raise InsufficientDataError("DSR requires at least 2 observations")

    sharpe_std = trial_sharpe_std if trial_sharpe_std is not None else 1.0
    sr0 = _expected_max_sharpe(max(n_trials, 1), sharpe_std)

    numerator = 1 - skewness * observed_sharpe + ((kurtosis - 1) / 4.0) * observed_sharpe**2
    denominator = n_observations - 1
    if denominator <= 0 or numerator < 0:
        return 0.0
    se_sr = math.sqrt(numerator / denominator)
    if se_sr == 0:
        return 1.0 if observed_sharpe > sr0 else 0.0

    z = (observed_sharpe - sr0) / se_sr
    return float(stats.norm.cdf(z))


def compute_pbo(performance_matrix: "np.ndarray") -> float:
    """`performance_matrix`: shape (n_trials, n_partitions); each cell is a per-partition
    performance statistic (e.g. per-fold Sharpe or net_return_bps) for that trial.
    Implements CSCV (Bailey, Borwein, Lopez de Prado, Salehipour, Zhu 2015).
    """
    matrix = np.asarray(performance_matrix, dtype=float)
    if matrix.ndim != 2:
        raise InsufficientDataError("performance_matrix must be 2-D (n_trials x n_partitions)")
    n_trials, n_partitions = matrix.shape
    if n_partitions < 2:
        raise InsufficientDataError("PBO requires at least 2 partitions (walk-forward folds)")
    if n_trials < 2:
        raise InsufficientDataError("PBO requires at least 2 trials to compare")

    if n_partitions % 2 != 0:
        matrix = matrix[:, :-1]
        n_partitions -= 1
    half = n_partitions // 2

    indices = list(range(n_partitions))
    logits = []
    for combo in combinations(indices, half):
        is_idx = list(combo)
        oos_idx = [i for i in indices if i not in combo]
        is_perf = matrix[:, is_idx].mean(axis=1)
        oos_perf = matrix[:, oos_idx].mean(axis=1)

        best_is_trial = int(np.argmax(is_perf))
        others_oos = np.delete(oos_perf, best_is_trial)
        omega = float((others_oos < oos_perf[best_is_trial]).sum()) / len(others_oos) if len(others_oos) else 0.5
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1 - omega)))

    return sum(1 for logit in logits if logit <= 0) / len(logits)


def performance_matrix_from_window_breakdowns(trial_window_sharpes: Dict[str, List[Optional[float]]]) -> "np.ndarray":
    """`trial_window_sharpes`: {trial_name: [sharpe_fold_1, sharpe_fold_2, ...]}. All
    trials must have the same number of folds; a missing (None) value is treated as 0.0
    (a strategy that took no trades in a fold neither gained nor lost).
    """
    if not trial_window_sharpes:
        raise InsufficientDataError("No trials supplied")
    lengths = {len(v) for v in trial_window_sharpes.values()}
    if len(lengths) != 1:
        raise InsufficientDataError("All trials must report the same number of walk-forward folds")

    rows = [[(v if v is not None else 0.0) for v in values] for values in trial_window_sharpes.values()]
    return np.array(rows, dtype=float)
