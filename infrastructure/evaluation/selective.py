"""Selective Prediction Metrics Infrastructure (Phase 23).

Calculates coverage, selective risk, abstention rate, precision at fixed coverage,
review yield, and false-positive rate among non-abstained predictions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SelectivePredictionMetrics(BaseModel):
    """Metrics evaluating selective prediction and abstention behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage: float = Field(ge=0.0, le=1.0)
    selective_risk: float = Field(ge=0.0, le=1.0)
    abstention_rate: float = Field(ge=0.0, le=1.0)
    precision_at_coverage: float = Field(ge=0.0, le=1.0)
    review_yield: float = Field(ge=0.0, le=1.0)
    fpr_non_abstained: float = Field(ge=0.0, le=1.0)


def calculate_selective_prediction_metrics(
    y_true: list[int],
    y_prob: list[float],
    accept_threshold: float = 0.8,
    reject_threshold: float = 0.2,
) -> SelectivePredictionMetrics:
    """Calculate selective prediction metrics.

    Probabilities between reject_threshold and accept_threshold are abstained for human review.
    """
    if not y_true or len(y_true) != len(y_prob):
        return SelectivePredictionMetrics(
            coverage=0.0,
            selective_risk=0.0,
            abstention_rate=1.0,
            precision_at_coverage=0.0,
            review_yield=0.0,
            fpr_non_abstained=0.0,
        )

    total = len(y_true)
    accepted_idx = [i for i, p in enumerate(y_prob) if p >= accept_threshold]
    rejected_idx = [i for i, p in enumerate(y_prob) if p <= reject_threshold]
    abstained_idx = [i for i, p in enumerate(y_prob) if reject_threshold < p < accept_threshold]

    non_abstained_count = len(accepted_idx) + len(rejected_idx)
    coverage = non_abstained_count / total if total > 0 else 0.0
    abstention_rate = len(abstained_idx) / total if total > 0 else 0.0

    # Errors among non-abstained predictions
    accepted_errors = sum(1 for i in accepted_idx if y_true[i] == 0)
    rejected_errors = sum(1 for i in rejected_idx if y_true[i] == 1)
    total_selective_errors = accepted_errors + rejected_errors

    selective_risk = (
        total_selective_errors / non_abstained_count if non_abstained_count > 0 else 0.0
    )

    # Precision on accepted
    tp = sum(1 for i in accepted_idx if y_true[i] == 1)
    prec_at_cov = tp / len(accepted_idx) if len(accepted_idx) > 0 else 0.0

    # Review yield: proportion of abstained items that are true positives requiring expert review
    abstained_tp = sum(1 for i in abstained_idx if y_true[i] == 1)
    review_yield = abstained_tp / len(abstained_idx) if len(abstained_idx) > 0 else 0.0

    # FPR among non-abstained
    true_negatives_count = sum(1 for i in (accepted_idx + rejected_idx) if y_true[i] == 0)
    fpr_non_abstained = accepted_errors / true_negatives_count if true_negatives_count > 0 else 0.0

    return SelectivePredictionMetrics(
        coverage=round(coverage, 4),
        selective_risk=round(selective_risk, 4),
        abstention_rate=round(abstention_rate, 4),
        precision_at_coverage=round(prec_at_cov, 4),
        review_yield=round(review_yield, 4),
        fpr_non_abstained=round(fpr_non_abstained, 4),
    )
