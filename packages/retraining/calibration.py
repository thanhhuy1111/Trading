"""Platt-scaling probability calibration, fit on the VALIDATION split only, never test.

Self-contained (no dependency on the retired `packages.prediction` stack): a 1-D logistic
regression of outcome ~ raw_probability via scikit-learn, ported from the same technique
`packages.prediction.calibration` used on the AI Trading Advisor branch this repo's
`research/accuracy-campaign-v1` branch reconciles work from.

Sign convention: `packages.intelligence.meta_label.LogisticRegressionMetaLabelService`
already ships (untested until now, since no artifact ever populated `calibration`) the
inference formula `probability = 1/(1+exp(a*raw_probability + b))`. A plain sklearn fit gives
`P(y=1|x) = sigmoid(coef*x + intercept) = 1/(1+exp(-(coef*x+intercept)))`. Matching that
existing, already-shipped inference formula requires storing `a=-coef`, `b=-intercept` here --
get this sign wrong and the artifact silently INVERTS every calibrated probability, which is
exactly the kind of defect this module's own test suite must catch.
"""

from typing import Dict, List, Optional


def fit_platt_scaling(raw_probabilities: List[float], outcomes: List[int]) -> Optional[Dict[str, object]]:
    """Returns `{"method": "platt", "a": float, "b": float}` ready to store directly in a
    `LogisticRegressionMetaLabelService` artifact's `calibration` field, or None if there
    isn't enough signal to fit (fewer than 2 outcome classes present) -- never a fabricated
    or degenerate calibration."""
    if len(raw_probabilities) != len(outcomes):
        raise ValueError("raw_probabilities and outcomes must be the same length")
    if len(set(outcomes)) < 2:
        return None

    import numpy as np
    from sklearn.linear_model import LogisticRegression

    x = np.array(raw_probabilities).reshape(-1, 1)
    y = np.array(outcomes)
    clf = LogisticRegression().fit(x, y)
    coef = float(clf.coef_[0][0])
    intercept = float(clf.intercept_[0])
    return {"method": "platt", "a": -coef, "b": -intercept}


def brier_score(probabilities: List[float], outcomes: List[int]) -> float:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")
    if not probabilities:
        raise ValueError("cannot score an empty sample")
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)) / len(probabilities)
