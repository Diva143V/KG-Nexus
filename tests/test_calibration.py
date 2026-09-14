"""Tests for Calibration and Selective Prediction Infrastructure (Phase 23)."""

from infrastructure.evaluation.calibration import (
    CalibrationReport,
    calculate_calibration_metrics,
)
from infrastructure.evaluation.selective import (
    calculate_selective_prediction_metrics,
)


def test_calculate_calibration_metrics():
    y_true = [1, 1, 1, 0, 0, 1, 0, 0, 1, 0]
    y_prob = [0.95, 0.9, 0.85, 0.1, 0.2, 0.7, 0.3, 0.15, 0.8, 0.4]

    metrics = calculate_calibration_metrics(y_true, y_prob, n_bins=5)
    assert 0.0 <= metrics.ece <= 1.0
    assert 0.0 <= metrics.brier_score <= 1.0
    assert metrics.precision > 0.0
    assert metrics.recall > 0.0
    assert len(metrics.bins) > 0


def test_calibration_report_snapshot_storage():
    metrics = calculate_calibration_metrics([1, 0], [0.9, 0.1])
    report = CalibrationReport(
        dataset_snapshot="snapshot_2026_01",
        split="test",
        entity_type="Gene",
        assertion_type="encodes",
        matcher_version="1.0.0",
        model_version="8b_v1",
        policy_version="bio_policy_v1",
        hardware="cuda_gpu",
        overall_metrics=metrics,
        by_entity_type={"Gene": metrics},
    )

    assert report.dataset_snapshot == "snapshot_2026_01"
    assert "Gene" in report.by_entity_type


def test_selective_prediction_metrics():
    y_true = [1, 1, 1, 0, 0, 1, 0, 0, 1, 0]
    # 0.5 is in the abstained zone (0.2 < p < 0.8)
    y_prob = [0.95, 0.9, 0.85, 0.1, 0.05, 0.5, 0.5, 0.15, 0.82, 0.5]

    metrics = calculate_selective_prediction_metrics(
        y_true, y_prob, accept_threshold=0.8, reject_threshold=0.2
    )

    assert 0.0 <= metrics.coverage <= 1.0
    assert 0.0 <= metrics.abstention_rate <= 1.0
    assert metrics.abstention_rate > 0.0  # Items with p=0.5 should be abstained
    assert 0.0 <= metrics.selective_risk <= 1.0
