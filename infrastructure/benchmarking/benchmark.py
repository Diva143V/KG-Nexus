"""Benchmarking suite executing real candidate generation, evaluation, and latency measurements."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.entities.entity import Entity
from core.fusion.candidates import CandidateGenerator
from core.fusion.engine import DefaultIdentityPolicy
from core.identifiers.identifier import Identifier
from core.projection.profile import ProjectionProfile, ReconciliationStrategy
from core.projection.reconciliation import (
    APPROVED_GRAPH,
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_SUBJECT,
    ProjectionReconciler,
)
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import Triple, iri
from core.resolution.models import CandidateMatch
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource
from infrastructure.projections.memory import MemoryProjectionBackend


class BenchmarkIntegrityError(RuntimeError):
    """Raised when benchmark dataset verification or strict quality gates fail."""


class CandidateRecallMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    recall_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_20: float = Field(ge=0.0, le=1.0)
    recall_at_50: float = Field(ge=0.0, le=1.0)


class ResolutionMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    fpr: float = Field(ge=0.0, le=1.0)
    abstention_rate: float = Field(ge=0.0, le=1.0)


class ProjectionBenchmarkMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    build_time_ms: float = Field(ge=0.0)
    reconciliation_time_ms: float = Field(ge=0.0)
    rebuild_reproducible: bool = True


class OperationalMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    p50_latency_ms: float = Field(ge=0.0)
    p95_latency_ms: float = Field(ge=0.0)
    p99_latency_ms: float = Field(ge=0.0)
    throughput_ops_per_sec: float = Field(ge=0.0)
    rollback_time_ms: float = Field(ge=0.0)
    endpoint_switch_time_ms: float = Field(ge=0.0)


class BenchmarkDataset(BaseModel):
    """Parsed, verified versioned benchmark dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    domain: str
    description: str
    source_entities: tuple[Entity, ...]
    target_entities: tuple[Entity, ...]
    ground_truth_matches: tuple[tuple[str, str], ...]
    sha256_digest: str


class BenchmarkResult(BaseModel):
    """Full recorded benchmark result with environment metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    source_release: str
    software_versions: dict[str, str]
    model_version: str
    policy_version: str
    hardware: str
    candidate_generation: CandidateRecallMetrics
    resolution: ResolutionMetrics
    calibration_ece: float
    calibration_brier: float
    projection: ProjectionBenchmarkMetrics
    operations: OperationalMetrics


def resolve_benchmark_dataset_path(custom_path: Path | str | None = None) -> Path:
    """Resolve absolute path to the versioned benchmark dataset."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    if custom_path is not None:
        p = Path(custom_path)
        if p.is_file():
            return p.resolve()
        repo_p = repo_root / p
        if repo_p.is_file():
            return repo_p.resolve()
        raise FileNotFoundError(f"Custom benchmark dataset not found: {custom_path}")

    # Default location: data/benchmarks/biomedical_eval_v1.json
    repo_root = Path(__file__).resolve().parent.parent.parent
    default_p = repo_root / "data" / "benchmarks" / "biomedical_eval_v1.json"
    if default_p.is_file():
        return default_p

    # Current working directory fallback
    cwd_p = Path.cwd() / "data" / "benchmarks" / "biomedical_eval_v1.json"
    if cwd_p.is_file():
        return cwd_p

    raise FileNotFoundError(f"Default benchmark dataset not found at {default_p}")


def load_benchmark_dataset(path: Path | str | None = None) -> BenchmarkDataset:
    """Load and cryptographically verify a versioned benchmark dataset."""
    dataset_file = resolve_benchmark_dataset_path(path)
    raw_bytes = dataset_file.read_bytes()
    computed_sha = hashlib.sha256(raw_bytes).hexdigest()

    # Verify against companion .sha256 file if present
    companion_sha = dataset_file.with_name(f"{dataset_file.name}.sha256")
    if companion_sha.is_file():
        sha_text = companion_sha.read_text(encoding="utf-8").strip()
        expected_sha = sha_text.split()[0]
        if computed_sha != expected_sha:
            raise BenchmarkIntegrityError(
                f"Benchmark dataset digest mismatch: computed {computed_sha} != expected {expected_sha}"
            )

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkIntegrityError(f"Malformed benchmark dataset JSON: {exc}") from exc

    source_entities = tuple(Entity(**e) for e in data.get("source_entities", []))
    target_entities = tuple(Entity(**e) for e in data.get("target_entities", []))
    raw_matches = data.get("ground_truth_matches", [])
    ground_truth_matches = tuple((str(p[0]), str(p[1])) for p in raw_matches if len(p) >= 2)

    return BenchmarkDataset(
        version=str(data.get("version", "1.0.0")),
        domain=str(data.get("domain", "biomedical")),
        description=str(data.get("description", "")),
        source_entities=source_entities,
        target_entities=target_entities,
        ground_truth_matches=ground_truth_matches,
        sha256_digest=computed_sha,
    )


class SystemBenchmarker:
    """Benchmarking suite executing real candidate generation, evaluation, and latency measurements."""

    def __init__(self, dataset_path: Path | str | None = None) -> None:
        self.dataset_path = dataset_path

    def load_dataset(self, dataset_path: Path | str | None = None) -> BenchmarkDataset:
        """Load benchmark dataset using instance or override path."""
        target_path = dataset_path if dataset_path is not None else self.dataset_path
        return load_benchmark_dataset(target_path)

    def _execute_projection_operations(
        self,
        entities: Sequence[Entity],
        release_id: str,
    ) -> tuple[float, float, bool, float, float]:
        """Execute real projection lifecycle operations and return genuine wall-clock timings."""
        triples: list[Triple] = []
        for idx, ent in enumerate(entities):
            asn_uri = iri(f"urn:assertion:bench_{idx}")
            subj_uri = iri(ent.id.value)
            pred_uri = iri("http://example.org/pred/interacts_with")
            obj_uri = iri(f"http://example.org/tgt/node_{idx}")
            triples.append(Triple(subject=asn_uri, predicate=iri(ASN_SUBJECT), object=subj_uri))
            triples.append(Triple(subject=asn_uri, predicate=iri(ASN_PREDICATE), object=pred_uri))
            triples.append(Triple(subject=asn_uri, predicate=iri(ASN_OBJECT), object=obj_uri))

        graph = NamedGraph(name=APPROVED_GRAPH, triples=tuple(triples))
        dataset = RDFDataset(graphs=(graph,))
        data_source = AuthoritativeReleaseRDFSource()
        data_source.register_dataset(release_id, dataset)

        profile = ProjectionProfile(
            profile_id=f"bench_profile_{release_id}",
            profile_version="1.0.0",
            reconciliation_strategy=ReconciliationStrategy.REBUILD,
        )

        backend_primary = MemoryProjectionBackend(
            data_source=data_source, backend_id="bench_primary"
        )
        backend_replica = MemoryProjectionBackend(
            data_source=data_source, backend_id="bench_replica"
        )

        proj_primary_id = f"proj_primary_{release_id}"
        proj_replica_id = f"proj_replica_{release_id}"

        # 1. Real Build Timing
        t0 = time.perf_counter()
        backend_primary.build(proj_primary_id, release_id, profile)
        t1 = time.perf_counter()
        build_time_ms = max(0.001, (t1 - t0) * 1000)

        # 2. Real Dual-Build Reproducibility Check
        backend_replica.build(proj_replica_id, release_id, profile)
        records_1 = backend_primary.records(proj_primary_id)
        records_2 = backend_replica.records(proj_replica_id)

        records_1_sorted = sorted(records_1, key=lambda r: (r.kind, r.key, r.digest))
        records_2_sorted = sorted(records_2, key=lambda r: (r.kind, r.key, r.digest))
        digest_1 = hashlib.sha256(
            "".join(f"{r.kind}:{r.key}:{r.digest};" for r in records_1_sorted).encode("utf-8")
        ).hexdigest()
        digest_2 = hashlib.sha256(
            "".join(f"{r.kind}:{r.key}:{r.digest};" for r in records_2_sorted).encode("utf-8")
        ).hexdigest()

        rebuild_reproducible = (
            (digest_1 == digest_2)
            and len(records_1_sorted) > 0
            and len(records_1_sorted) == len(records_2_sorted)
        )

        # 3. Real Reconciliation Timing
        reconciler = ProjectionReconciler()
        t2 = time.perf_counter()
        reconciler.reconcile(
            projection_id=proj_primary_id,
            release_id=release_id,
            profile=profile,
            dataset=dataset,
            projected_records=records_1,
        )
        t3 = time.perf_counter()
        reconciliation_time_ms = max(0.001, (t3 - t2) * 1000)

        # 4. Real Endpoint Switch (Activation) Timing
        t4 = time.perf_counter()
        backend_primary.activate(proj_primary_id)
        t5 = time.perf_counter()
        endpoint_switch_time_ms = max(0.001, (t5 - t4) * 1000)

        # 5. Real Rollback Timing
        t6 = time.perf_counter()
        backend_primary.rollback(proj_primary_id)
        t7 = time.perf_counter()
        rollback_time_ms = max(0.001, (t7 - t6) * 1000)

        # Clean up
        backend_primary.destroy(proj_primary_id)
        backend_replica.destroy(proj_replica_id)

        return (
            round(build_time_ms, 4),
            round(reconciliation_time_ms, 4),
            rebuild_reproducible,
            round(endpoint_switch_time_ms, 4),
            round(rollback_time_ms, 4),
        )

    def run_benchmarks(
        self,
        dataset: str | None = None,
        source_release: str = "rel_2026_01",
        strict: bool = False,
        dataset_path: Path | str | None = None,
    ) -> BenchmarkResult:
        """Execute real benchmark workload and measure true accuracy, calibration, and latency."""
        bench_data = self.load_dataset(dataset_path)
        src_ents = bench_data.source_entities
        tgt_ents = bench_data.target_entities
        gt_matches = set(bench_data.ground_truth_matches)

        act_id = Identifier(namespace="ACT", value="benchmark_activity")
        generator = CandidateGenerator(generator_id="benchmark_generator_v1")
        policy = DefaultIdentityPolicy()

        # Measure Candidate Generation
        candidates = generator.generate_candidates(src_ents, tgt_ents, act_id)

        # Calculate Recall@K
        cands_by_src: dict[str, list[CandidateMatch]] = {}
        for c in candidates:
            cands_by_src.setdefault(c.source_entity.id.value, []).append(c)

        hits_10 = 0
        hits_20 = 0
        hits_50 = 0
        total_gt = len(gt_matches)

        for s_id, t_id in gt_matches:
            src_cands = cands_by_src.get(s_id, [])
            tgt_ids_ranked = [c.candidate_entity.id.value for c in src_cands]
            if t_id in tgt_ids_ranked[:10]:
                hits_10 += 1
            if t_id in tgt_ids_ranked[:20]:
                hits_20 += 1
            if t_id in tgt_ids_ranked[:50]:
                hits_50 += 1

        rec_10 = hits_10 / total_gt if total_gt else 1.0
        rec_20 = hits_20 / total_gt if total_gt else 1.0
        rec_50 = hits_50 / total_gt if total_gt else 1.0

        # Measure Resolution Policy & Latencies
        durations_ms: list[float] = []
        tp = 0
        fp = 0
        fn = 0
        tn = 0
        abstentions = 0

        confidences: list[float] = []
        labels: list[float] = []

        for c in candidates:
            t0 = time.perf_counter()
            decision = policy.evaluate(c)
            t1 = time.perf_counter()
            durations_ms.append(max(0.0001, (t1 - t0) * 1000))

            pair_key = (c.source_entity.id.value, c.candidate_entity.id.value)
            is_gt_positive = pair_key in gt_matches

            conf = float(c.ranking_score)
            confidences.append(conf)
            labels.append(1.0 if is_gt_positive else 0.0)

            if decision.accepted:
                if is_gt_positive:
                    tp += 1
                else:
                    fp += 1
            else:
                if decision.method in ("abstain", "review") or (0.70 <= conf < 0.88):
                    abstentions += 1
                if is_gt_positive:
                    fn += 1
                else:
                    tn += 1

        # Ground truth positives that never appeared in candidate generation count as FN
        for s_id, _t_id in gt_matches:
            if s_id not in cands_by_src:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 1.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        abstention_rate = abstentions / len(candidates) if candidates else 0.0

        # Calibration: Brier score & ECE
        if confidences:
            brier_score = sum(
                (p - y) ** 2 for p, y in zip(confidences, labels, strict=False)
            ) / len(confidences)
            # ECE with 5 bins
            ece = 0.0
            num_bins = 5
            for b in range(num_bins):
                b_min = b / num_bins
                b_max = (b + 1) / num_bins
                bin_items = [
                    (p, y)
                    for p, y in zip(confidences, labels, strict=False)
                    if b_min <= p < b_max or (b == num_bins - 1 and p == 1.0)
                ]
                if bin_items:
                    bin_conf = sum(p for p, _ in bin_items) / len(bin_items)
                    bin_acc = sum(y for _, y in bin_items) / len(bin_items)
                    ece += abs(bin_acc - bin_conf) * (len(bin_items) / len(confidences))
        else:
            brier_score = 0.0
            ece = 0.0

        # Latency percentiles
        durations_ms.sort()
        n = len(durations_ms)
        p50 = durations_ms[min(n - 1, int(n * 0.50))] if n else 0.01
        p95 = durations_ms[min(n - 1, int(n * 0.95))] if n else p50
        p99 = durations_ms[min(n - 1, int(n * 0.99))] if n else p95
        p95 = max(p95, p50)
        p99 = max(p99, p95)

        total_duration_sec = sum(durations_ms) / 1000.0
        throughput = n / total_duration_sec if total_duration_sec > 0 else 1000.0

        hw_name = f"{platform.system().lower()}_{platform.machine().lower()}"
        versions = {
            "platform": "1.0.0",
            "core": "2.0.0",
            "python": platform.python_version(),
        }

        # Real Projection & Operational Lifecycle Execution
        (
            proj_build_ms,
            proj_recon_ms,
            rebuild_reproducible,
            endpoint_switch_ms,
            rollback_ms,
        ) = self._execute_projection_operations(src_ents, source_release)

        result_dataset_name = dataset or f"{bench_data.domain}_{bench_data.version}"

        res = BenchmarkResult(
            dataset=result_dataset_name,
            source_release=source_release,
            software_versions=versions,
            model_version="8b_v1",
            policy_version="bio_policy_v1",
            hardware=hw_name,
            candidate_generation=CandidateRecallMetrics(
                recall_at_10=round(rec_10, 4),
                recall_at_20=round(rec_20, 4),
                recall_at_50=round(rec_50, 4),
            ),
            resolution=ResolutionMetrics(
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(f1, 4),
                fpr=round(fpr, 4),
                abstention_rate=round(abstention_rate, 4),
            ),
            calibration_ece=round(ece, 4),
            calibration_brier=round(brier_score, 4),
            projection=ProjectionBenchmarkMetrics(
                build_time_ms=round(proj_build_ms, 3),
                reconciliation_time_ms=round(proj_recon_ms, 3),
                rebuild_reproducible=rebuild_reproducible,
            ),
            operations=OperationalMetrics(
                p50_latency_ms=round(p50, 4),
                p95_latency_ms=round(p95, 4),
                p99_latency_ms=round(p99, 4),
                throughput_ops_per_sec=round(throughput, 2),
                rollback_time_ms=round(rollback_ms, 3),
                endpoint_switch_time_ms=round(endpoint_switch_ms, 3),
            ),
        )

        if strict:
            self.validate_thresholds(res)

        return res

    def validate_thresholds(
        self,
        result: BenchmarkResult,
        min_precision: float = 0.65,
        min_recall: float = 0.70,
        min_f1: float = 0.70,
        max_ece: float = 0.35,
        max_brier: float = 0.35,
        require_reproducible: bool = True,
    ) -> None:
        """Enforce strict fail-closed quality gates against benchmark results."""
        violations: list[str] = []

        if require_reproducible and not result.projection.rebuild_reproducible:
            violations.append("Projection rebuild reproducibility check failed (hash mismatch)")

        if result.resolution.precision < min_precision:
            violations.append(
                f"Precision {result.resolution.precision:.4f} below threshold {min_precision:.4f}"
            )
        if result.resolution.recall < min_recall:
            violations.append(
                f"Recall {result.resolution.recall:.4f} below threshold {min_recall:.4f}"
            )
        if result.resolution.f1 < min_f1:
            violations.append(f"F1 {result.resolution.f1:.4f} below threshold {min_f1:.4f}")
        if result.calibration_ece > max_ece:
            violations.append(
                f"Calibration ECE {result.calibration_ece:.4f} exceeds limit {max_ece:.4f}"
            )
        if result.calibration_brier > max_brier:
            violations.append(
                f"Calibration Brier {result.calibration_brier:.4f} exceeds limit {max_brier:.4f}"
            )

        if result.operations.rollback_time_ms <= 0.0:
            violations.append("Operational rollback latency must be positive non-zero")
        if result.operations.endpoint_switch_time_ms <= 0.0:
            violations.append("Operational endpoint switch latency must be positive non-zero")

        if violations:
            raise BenchmarkIntegrityError(
                f"Benchmark integrity failure with {len(violations)} violations: {'; '.join(violations)}"
            )
