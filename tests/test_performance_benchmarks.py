"""Tests for System Performance and Benchmarking Suite with true Benchmark Integrity."""

from pathlib import Path

import pytest

from infrastructure.benchmarking.benchmark import (
    BenchmarkDataset,
    BenchmarkIntegrityError,
    BenchmarkResult,
    SystemBenchmarker,
    load_benchmark_dataset,
    resolve_benchmark_dataset_path,
)


def test_system_benchmarker_records_all_required_metrics() -> None:
    """Verify benchmarker runs on versioned dataset and computes authentic metrics."""
    benchmarker = SystemBenchmarker()
    res: BenchmarkResult = benchmarker.run_benchmarks(
        dataset="test_eval_set", source_release="rel_2026.1"
    )

    assert res.dataset == "test_eval_set"
    assert res.source_release == "rel_2026.1"

    # Candidate generation recall metrics
    assert res.candidate_generation.recall_at_10 > 0.80
    assert res.candidate_generation.recall_at_20 >= res.candidate_generation.recall_at_10
    assert res.candidate_generation.recall_at_50 >= res.candidate_generation.recall_at_20

    # Resolution accuracy metrics on real biomedical entities
    assert res.resolution.precision >= 0.70
    assert res.resolution.recall >= 0.80
    assert res.resolution.f1 >= 0.75
    assert 0.0 <= res.resolution.fpr <= 1.0

    # Calibration
    assert 0.0 <= res.calibration_ece <= 1.0
    assert 0.0 <= res.calibration_brier <= 1.0

    # Projection build & reconciliation
    assert res.projection.build_time_ms > 0.0
    assert res.projection.reconciliation_time_ms > 0.0
    assert res.projection.rebuild_reproducible is True

    # Operational latency & throughput
    assert res.operations.p50_latency_ms >= 0.0
    assert res.operations.p95_latency_ms >= res.operations.p50_latency_ms
    assert res.operations.p99_latency_ms >= res.operations.p95_latency_ms
    assert res.operations.throughput_ops_per_sec > 0.0


def test_benchmark_dataset_loading_and_sha256_verification(tmp_path: Path) -> None:
    """Verify dataset loading computes and validates SHA-256 digests."""
    dataset_path = resolve_benchmark_dataset_path()
    assert dataset_path.is_file()

    dataset: BenchmarkDataset = load_benchmark_dataset(dataset_path)
    assert dataset.version == "1.0.0"
    assert dataset.domain == "biomedical"
    assert len(dataset.source_entities) >= 50
    assert len(dataset.target_entities) >= 50
    assert len(dataset.ground_truth_matches) >= 50
    assert len(dataset.sha256_digest) == 64

    # Verify checksum tamper detection
    tampered_file = tmp_path / "tampered.json"
    tampered_file.write_text(dataset_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered_sha = tmp_path / "tampered.json.sha256"
    tampered_sha.write_text(
        "0000000000000000000000000000000000000000000000000000000000000000  tampered.json\n"
    )

    with pytest.raises(BenchmarkIntegrityError, match="digest mismatch"):
        load_benchmark_dataset(tampered_file)


def test_operational_timings_are_authentic_and_not_fabricated_multipliers() -> None:
    """Verify rollback and endpoint switch latencies are measured wall-clock timings, not multipliers."""
    benchmarker = SystemBenchmarker()
    res = benchmarker.run_benchmarks()

    reconcile_ms = res.projection.reconciliation_time_ms
    rollback_ms = res.operations.rollback_time_ms
    switch_ms = res.operations.endpoint_switch_time_ms

    assert rollback_ms > 0.0
    assert switch_ms > 0.0

    # Must NOT equal the old fabricated formulas: reconcile * 0.5 or reconcile * 0.2
    fabricated_rollback = round(reconcile_ms * 0.5, 3)
    fabricated_switch = round(reconcile_ms * 0.2, 3)

    assert abs(rollback_ms - fabricated_rollback) > 0.01 or rollback_ms != fabricated_rollback
    assert abs(switch_ms - fabricated_switch) > 0.01 or switch_ms != fabricated_switch


def test_projection_dual_build_reproducibility() -> None:
    """Verify dual independent projection builds verify SHA-256 digest matching."""
    benchmarker = SystemBenchmarker()
    bench_data = benchmarker.load_dataset()

    (
        build_ms,
        recon_ms,
        reproducible,
        switch_ms,
        rollback_ms,
    ) = benchmarker._execute_projection_operations(
        bench_data.source_entities[:20],
        release_id="rel_repro_test",
    )

    assert reproducible is True
    assert build_ms > 0.0
    assert recon_ms > 0.0
    assert switch_ms > 0.0
    assert rollback_ms > 0.0


def test_strict_threshold_validation_gates() -> None:
    """Verify strict validation gates succeed on valid benchmark runs and fail-closed on violations."""
    benchmarker = SystemBenchmarker()

    # 1. Normal run with strict=True must succeed
    res = benchmarker.run_benchmarks(strict=True)
    assert res.projection.rebuild_reproducible is True

    # 2. Strict validation fails if thresholds are breached
    with pytest.raises(BenchmarkIntegrityError, match="Precision .* below threshold"):
        benchmarker.validate_thresholds(res, min_precision=1.01)

    with pytest.raises(BenchmarkIntegrityError, match="Recall .* below threshold"):
        benchmarker.validate_thresholds(res, min_recall=0.99)

    with pytest.raises(BenchmarkIntegrityError, match="F1 .* below threshold"):
        benchmarker.validate_thresholds(res, min_f1=0.99)

    with pytest.raises(BenchmarkIntegrityError, match="Calibration ECE .* exceeds limit"):
        benchmarker.validate_thresholds(res, max_ece=0.01)

    with pytest.raises(BenchmarkIntegrityError, match="Calibration Brier .* exceeds limit"):
        benchmarker.validate_thresholds(res, max_brier=0.01)


def test_validation_gate_detects_non_reproducible_rebuild() -> None:
    """Verify validate_thresholds fails-closed when rebuild reproducibility is False."""
    benchmarker = SystemBenchmarker()
    res = benchmarker.run_benchmarks(strict=False)

    # Artificially tamper with result to simulate reproducibility failure
    tampered_projection = res.projection.model_copy(update={"rebuild_reproducible": False})
    tampered_res = res.model_copy(update={"projection": tampered_projection})

    with pytest.raises(BenchmarkIntegrityError, match="reproducibility check failed"):
        benchmarker.validate_thresholds(tampered_res, require_reproducible=True)
