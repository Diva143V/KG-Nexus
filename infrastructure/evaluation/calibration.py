"""Calibration and Evaluation Infrastructure (Phase 23).

Computes ECE, Brier score, reliability diagrams, and precision-recall metrics
by entity type and source pair without mutating runtime thresholds.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CalibrationMetrics(BaseModel):
    """Calibration and resolution accuracy metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ece: float = Field(ge=0.0, le=1.0)
    brier_score: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    bins: tuple[dict[str, float], ...] = Field(default_factory=tuple)


def calculate_calibration_metrics(
    y_true: list[int],
    y_prob: list[float],
    n_bins: int = 10,
) -> CalibrationMetrics:
    """Calculate ECE, Brier score, Precision, Recall, F1, and reliability diagram bins."""
    if not y_true or len(y_true) != len(y_prob):
        return CalibrationMetrics(ece=0.0, brier_score=0.0, precision=0.0, recall=0.0, f1=0.0)

    n = len(y_true)
    # Brier Score
    brier = sum((p - y) ** 2 for p, y in zip(y_prob, y_true, strict=False)) / n

    # ECE and Binning
    bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
    ece = 0.0
    bins_data: list[dict[str, float]] = []

    for i in range(n_bins):
        low, high = bin_boundaries[i], bin_boundaries[i + 1]
        bin_items = [
            (y, p)
            for y, p in zip(y_true, y_prob, strict=False)
            if low <= p < high or (i == n_bins - 1 and p == high)
        ]
        if bin_items:
            bin_size = len(bin_items)
            acc = sum(y for y, _ in bin_items) / bin_size
            conf = sum(p for _, p in bin_items) / bin_size
            ece += (bin_size / n) * abs(acc - conf)
            bins_data.append(
                {
                    "bin_lower": low,
                    "bin_upper": high,
                    "accuracy": acc,
                    "confidence": conf,
                    "count": float(bin_size),
                }
            )

    # Precision, Recall, F1 at default threshold 0.5
    tp = sum(1 for y, p in zip(y_true, y_prob, strict=False) if y == 1 and p >= 0.5)
    fp = sum(1 for y, p in zip(y_true, y_prob, strict=False) if y == 0 and p >= 0.5)
    fn = sum(1 for y, p in zip(y_true, y_prob, strict=False) if y == 1 and p < 0.5)

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    return CalibrationMetrics(
        ece=round(ece, 4),
        brier_score=round(brier, 4),
        precision=round(prec, 4),
        recall=round(rec, 4),
        f1=round(f1, 4),
        bins=tuple(bins_data),
    )


class CalibrationReport(BaseModel):
    """Full snapshot of evaluation calibration metadata and metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_snapshot: str
    split: str
    entity_type: str
    assertion_type: str
    matcher_version: str
    model_version: str
    policy_version: str
    hardware: str
    overall_metrics: CalibrationMetrics
    by_entity_type: dict[str, CalibrationMetrics] = Field(default_factory=dict)
    by_source_pair: dict[str, CalibrationMetrics] = Field(default_factory=dict)
