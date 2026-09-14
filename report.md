# Production Readiness Implementation Report

## Scope

This report summarizes the production-readiness work implemented in the repository after the audit and plan were created.

`audit1.md` was not read or modified.

## Executive Status

The platform has been materially improved, but the entire production-readiness plan is **not yet complete**.

Current verified status:

- Full test suite: **863 passed**.
- Strict mypy: **clean across production packages (254 source files)**.
- Repository-wide Ruff: **clean** and formatted.
- Fusion correctness: substantially improved.
- Real semantic embeddings: implemented with pluggable hybrid providers (Ollama, HuggingFace, test double) and fail-closed contract.
- Graph and fusion-result persistence: implemented with SQLite.
- Durable Artifact & Assertion persistence: content-addressed SHA-256 storage, typed AssertionStore with state transitions, migration scripts, and backup/restore.
- Real projection execution & consolidation: canonicalized `ProjectionBackend` protocol, lifecycle-upgraded memory backend, durable `DurableProjectionStore`, authoritative RDF snapshot compiler.
- Full 13-stage release activation: all 13 stages execute real services backed by `ArtifactStore`, `AssertionStore`, `GraphStore`, `DurableProjectionStore`, and `ReleaseManager`, with non-destructive canary rollback in stage 13 and fail-closed release quarantine.
- Full projection-aware rollback in REST API: coordinated restoration of `GraphStore` snapshots and `DurableProjectionStore` projection manifests across registered backends via `POST /api/release/rollback`, plus `GET /api/projections/active`.
- Candidate release creation: implemented as an explicit `CANDIDATE` lifecycle record.
- Benchmark integrity and honest evaluation: real versioned biomedical dataset, SHA-256 verification, true dual-build projection reproducibility, zero fabricated multipliers, fail-closed validation gates.
- API failure behavior: honest, deterministic, fail-closed.
- Full production deployment readiness: **not achieved yet**.

The remaining blockers are primarily authentication/authorization and production deployment server.


## 1. Fusion Correctness Fixes

### Literal assertions now survive fusion

Problem:

Literal assertions were normalized and counted but were not reliably carried through meaning alignment and canonicalization.

Implementation:

- `MeaningAligner.align_assertions()` now processes both relational and literal assertions.
- Attribute mappings are applied to literal predicates.
- `Canonicalizer` attaches normalized literal values to canonical entity properties.
- Literal values from both graphs are merged instead of one graph overwriting the other.
- Single values remain scalar for compatibility; multiple values are retained as lists.

Primary files:

- `core/fusion/meaning_aligner.py`
- `core/fusion/canonicalizer.py`
- `core/fusion/normalizer.py`

Validation:

- `tests/test_fusion_critical_bugfixes.py`
- `tests/test_fusion_stage1_normalization.py`

### Class and attribute mapping fixes

Problem:

Class mapping lookup used an incompatible key format, so configured mappings could silently fail. Attribute mapping existed but was not active.

Implementation:

- Class lookup now uses the configured `graph_a`/`graph_b` role keys.
- Attribute alignment is applied to literal assertions.
- Ontology shortage fallback behavior is configuration-driven.

### Configured candidate weights now affect scoring

Problem:

Candidate scoring used hardcoded structural and embedding multipliers instead of configured weights.

Implementation:

- Composite scores now use `exact_id_weight`, `label_similarity_weight`, `structural_similarity_weight`, and `embedding_weight`.
- Matching threshold configuration is consumed by candidate generation.

### Graph identity handling improved

Problem:

Conflict precedence depended on assertion IDs containing strings such as `rel_graph_a` and `rel_graph_b`.

Implementation:

- Fusion passes explicit graph identifiers into canonicalization and conflict resolution.
- Graph precedence tests cover arbitrary custom graph IDs.

## 2. Parser and Configuration Fixes

### Parser registry is now active

Problem:

`GraphFusionService` instantiated `ParserRegistry` but directly constructed parser classes, bypassing custom registrations.

Implementation:

- Format aliases are normalized to registered media types.
- Parsing is routed through `ParserRegistry.parse()`.
- Unsupported formats now raise an error instead of silently falling through to JSON-LD.

Primary file:

- `core/fusion/service.py`

### Source validation is enforced

Problem:

`regex_pattern` and `require_content_hash` were declared in configuration but not enforced.

Implementation:

- Added `validate_source_uri()`.
- Configured source URI regexes are applied during normalization.
- Sources requiring a content hash are rejected when no digest is supplied.

Primary files:

- `core/resources/source_node.py`
- `core/fusion/normalizer.py`
- `sdk/domain_config.py`

Validation:

- `tests/test_source_config_enforcement.py`
- Existing source identity tests continue to pass.

## 3. Durable Storage and Release Persistence

### SQLite graph store

Problem:

The active graph was stored in a mutable process-local dictionary, so data disappeared on restart and concurrent processes could not share state.

Implementation:

Added `infrastructure/storage/graph_store.py`, which provides:

- Durable active graph storage.
- Transactional graph replacement.
- Persisted rollback snapshots.
- Restart-safe reads.
- SQLite locking for serialized write operations.
- Explicit reset support for isolated tests/development.

The API now reads and writes through `GraphStore` instead of using process-local graph data as the source of truth.

### Persisted fusion releases

Problem:

Fusion output was only placed in the active graph store and was not retrievable as a release record.

Implementation:

- Complete fusion payloads are persisted by release ID.
- `GET /api/releases/{release_id}` retrieves persisted release payloads.
- Release records are immutable.
- Reusing the same deterministic release identity replays the persisted result.
- Conflicting payloads under the same identity are rejected.

### Deterministic and idempotent fusion IDs

Problem:

Run IDs were timestamp-based, which could collide within a second and did not support reliable request replay.

Implementation:

Run identity is derived from stable inputs:

- Graph IDs.
- Assertion identity data.
- Domain configuration.
- Conflict mode.

Volatile assertion timestamps are excluded from the identity calculation.

Validation:

- `tests/test_graph_store.py`
- `tests/test_ui_api.py`
- Identical fusion requests are tested for idempotent release identity.

## 4. Release Lifecycle Improvements

### Candidate release records

Problem:

Fusion results were not connected to the repository's existing immutable release lifecycle models.

Implementation:

- Each persisted fusion result creates a `Release` in `CANDIDATE` status.
- A `ReleaseManifest` is attached with plugin and lockfile references.
- Lifecycle data is stored with the persisted fusion payload.
- The implementation does not falsely mark the result as validated or published.

This is an honest intermediate state: candidate creation is real, but projection-dependent lifecycle transitions remain blocked until their services exist.

### Release replay and immutable identity

Latest implementation:

- Fusion run IDs are derived from stable graph/assertion/configuration identity rather than wall-clock seconds.
- Volatile provenance timestamps are excluded from the identity digest.
- Repeated identical submissions return the persisted release payload.
- A conflicting payload using an existing release identity is rejected.
- The API now creates a real candidate lifecycle record using `ReleaseManager` and `ReleaseManifest`.

Validation:

- Identical-request replay is covered by `tests/test_ui_api.py`.
- Lifecycle persistence is covered by the graph-store and API tests.

## 5. API and UI Reliability Fixes

### Removed fabricated initial graph data

The API and graph explorer no longer start with fabricated biomedical nodes and edges. The graph begins empty and is populated from ingestion or fusion output.

### Honest model availability

Problem:

The API previously returned fabricated model availability and a fabricated fallback answer.

Implementation:

- Ollama discovery returns `unavailable` when no models are found.
- Query failures return an error/503 response rather than a fake verified answer.
- The verifier returns explicit abstention when no model provider is configured.
- Alignment verification returns HTTP 503 when the provider is unavailable.

### Real rollback request

Problem:

The UI rollback button only rendered a fabricated success object.

Implementation:

- UI sends `POST /api/release/rollback`.
- API restores the previous persisted SQLite graph snapshot.
- Response reports `durability: sqlite`.
- The UI displays backend status instead of inventing success.

### Honest pipeline progress

Problem:

The UI marked stages complete on a timer independent of backend results.

Implementation:

- Timer-driven success animation was removed.
- Stage badges are updated from returned backend stage statuses.

## 6. API Hardening

Implemented:

- Configurable maximum request body size.
- Invalid `Content-Length` handling.
- Configurable CORS origin instead of unconditional wildcard CORS.
- `/health` endpoint reporting API and storage status.
- Explicit validation for missing graph content and missing query/model fields.

Primary file:

- `infrastructure/api/server.py`

## 7. Test and Quality Improvements

The test suite grew from the earlier 784-test baseline to:

- 791 tests after the first implementation phase.
- 793, 794, 795, 797, and finally **799 passing tests** as persistence, lifecycle, source validation, idempotency, and API hardening tests were added.

New or expanded coverage includes:

- Literal survival through fusion.
- Attribute and class mapping execution.
- Configured candidate weights.
- Custom graph IDs.
- SQLite restart persistence.
- SQLite rollback behavior.
- Persisted release retrieval.
- Candidate lifecycle records.
- Identical-request idempotency.
- Source regex enforcement.
- Required content hash enforcement.
- API health and unavailable-model behavior.

Strict mypy now passes across all production packages: **242 source files checked with no errors**.

Additional quality fixes:

- Corrected licensing source-ID typing.
- Corrected optional transformed predicate handling in projection reconciliation.
- Corrected biomedical evidence category typing and default mapping inference.
- Cleaned Ruff issues in those touched files.
- Applied Ruff automatic fixes and formatting across the repository.
- Corrected unused locals, import placement, loop variables, and benchmark lint issues.
- Configured Ruff to use the formatter as the line-length authority by ignoring duplicate E501 diagnostics.

## 8. Real Neural and Pluggable Embeddings

### Pluggable hybrid provider architecture

Problem:

The optional embedding path in candidate matching used lexical string similarity as a mock while pretending to compute vector embeddings.

Implementation:

- Added `contracts/embeddings.py` defining `EmbeddingProvider` protocol, `EmbeddingModelMetadata`, and `EmbeddingProviderUnavailableError`.
- Implemented `infrastructure/embeddings/`:
  - `OllamaEmbeddingProvider`: Zero-dependency local Ollama HTTP embedding caller.
  - `HuggingFaceEmbeddingProvider`: In-process `sentence-transformers` loader for SOTA models (`bge-large-en-v1.5`, PubMedBERT, BioLinkBERT).
  - `DeterministicTestEmbeddingProvider`: Deterministic feature-hash test double for fast offline CI.
  - `resolver.py`: Pluggable resolver registered with contracts.
- Added `build_entity_surface_text` in `CandidateFinder`: Structured contextual surfaces (`label [kind]. Aliases: ... Description: ...`).
- Batch pre-computation: Entities from both graphs are batch-embedded upfront.
- True cosine similarity: Dot product of unit-normalized vectors.
- Semantic candidate discovery: Discovers candidate pairs with high cosine similarity ($\ge$ threshold) even when labels differ completely.
- Strict fail-closed contract: If embeddings are enabled and the provider/model cannot be reached, raises `EmbeddingProviderUnavailableError` (no silent degradation).
- Observability: Added `GET /api/embeddings/status` and `/health` reporting.

Validation:

- `tests/test_embedding_providers.py` (7 tests).
- `tests/test_candidate_finder_embeddings.py` (4 tests).
- `tests/test_architecture.py` (3 tests).

## 9. Durable Artifact and Assertion Persistence

### Content-addressed artifact repository and durable typed assertions

Problem:

Previously, only whole fusion result JSON blobs were persisted in `fusion_runs`. Raw source files, immutable ingested artifacts, granular typed assertions, and individual assertion state transitions were ephemeral and not queryable across releases.

Implementation:

- Added `contracts/artifacts.py` defining `ArtifactStore` protocol, `ArtifactMetadata`, and `ArtifactIntegrityError`.
- Created `infrastructure/storage/artifact_store.py`:
  - Content-addressed SHA-256 binary storage with verified integrity checks.
  - File payload backing in configurable storage directories.
  - SQLite metadata index with release foreign keys.
  - De-duplication of identical artifact blobs across releases.
- Implemented `infrastructure/storage/assertion_store.py`:
  - SQLite schema migration `003_artifacts_and_assertions.sql` with `artifacts`, `assertions`, `assertion_state_events`, and `release_assertions` tables.
  - Durable typed assertion persistence (`id`, `subject`, `predicate`, `object`, `assertion_type`, `state`, `confidence`, `provenance_id`, `version`).
  - Auditable lifecycle transitions: `RECORDED -> CANDIDATE -> VALIDATED -> CANONICAL -> RETIRED` with monotonic timestamps and actor metadata.
  - Many-to-many release linkage through `release_assertions`.
  - Atomic bulk insertion and rollback transactions.
- Developed `infrastructure/storage/backup.py`:
  - Complete database backup and restore CLI utility with VACUUM INTO, checksum verification, and foreign-key integrity checks.

Validation:

- `tests/test_durable_artifact_store.py` (5 tests).
- `tests/test_durable_assertion_store.py` (7 tests).

## 10. Real Projection Execution and Lifecycle Consolidation

### Canonical projection backend protocol, durable manifests, and pipeline activation

Problem:

The repository had competing projection abstractions (`core/projection` vs `core/projections`), mock implementations (`MemoryProjectionBackend` was a dictionary store with fake passes), unpersisted manifests, projections built directly from request memory rather than authoritative RDF/assertions, and release pipeline stages 9-13 did not execute real projection builds, validations, or reconciliation.

Implementation:

- Canonicalized the projection protocol in `contracts/projections.py`:
  - Standardized `ProjectionBackend(Protocol)` requiring `build()`, `validate()`, `records()`, `activate()`, `rollback()`, and `destroy()`.
  - Re-exported via `core/projection/backend.py` and `sdk/projection_backend.py`.
- Upgraded `MemoryProjectionBackend` (`infrastructure/projections/memory.py`):
  - Tracks complete candidate, active, and retained projection states.
  - Enforces schema and integrity validation during `validate()`.
  - Retains legacy backward-compatibility methods (`write`, `read`, `delete`).
- Durable projection store (`infrastructure/storage/projection_store.py`):
  - SQLite migration `004_projection_manifests.sql` tracking `release_id`, `backend_id`, `schema_version`, `status`, `input_digest`, `output_digest`, `record_count`, `manifest_json`, and timestamps with cascade FKs.
- Authoritative RDF data sourcing (`infrastructure/projections/data_source.py`):
  - Added `AuthoritativeReleaseRDFSource` querying `AssertionStore` by release ID and compiling authoritative `RDFDataset` snapshots via `RDFReleaseWriter`.
- Pipeline stages 9–13 activation (`infrastructure/release/pipeline.py`):
  - **Stage 9 (RDF Snapshot)**: Compiles and serializes an immutable RDF snapshot from authoritative persisted assertions, computing deterministic SHA-256 digests.
  - **Stage 10 (Projection Build & Validation)**: Executes real projection `build()` and `validate()` across configured projection backends, recording manifests in `DurableProjectionStore`.
  - **Stage 11 (Reconciliation)**: Reconciles projection record counts and entity sets against the authoritative RDF dataset.
  - **Stage 12 (Endpoint Activation)**: Invokes backend `activate()` to promote candidates to active serving endpoints.
  - **Stage 13 (Rollback Verification)**: Verifies backend `rollback()` contracts and snapshot restoration capability.
  - Strict `ReleaseGate` enforcement: Injected failure at any stage marks the release as `QUARANTINED` and halts publication.

Validation:

- `tests/test_projection_execution.py` (7 tests).

## 11. Full 13-Stage Release Pipeline Activation with Durable Persistence

### Complete service orchestration replacing mock stages 1–8 and enforcing formal release lifecycle

Problem:

While stages 9–13 had been connected to projection backends, stages 1 through 8 remained partially mock or disconnected from the durable storage layer. Artifacts were not content-addressed into `ArtifactStore`, assertions were not persisted into `AssertionStore` with formal state events, formal lifecycle transitions in `ReleaseManager` were bypassed, and injected failures did not guarantee release quarantine in `GraphStore`.

Implementation:

- **End-to-End Release Pipeline (`infrastructure/release/pipeline.py`)**:
  - **Stage 1 (Artifact Ingestion)**: Ingests raw input payloads or synthesizes domain pack ontology/component documents, computing SHA-256 digests and persisting immutable content into `DurableArtifactStore`.
  - **Stage 2 (Record Normalization)**: Verifies domain manifest compatibility and normalizes schema definitions via `PluginLoader`.
  - **Stage 3 (Candidate Generation)**: Executes candidate matching logic with configured threshold and similarity weights.
  - **Stage 4 (Assertion Creation)**: Produces typed `Assertion` instances with complete `Provenance` (`agent_id`, `activity_id`, `source_artifact_id`, `asserted_at`) and primary `Evidence` references.
  - **Stage 5 (State Transitions)**: Emits append-only `AssertionStateEvent` transitions (`None -> CANDIDATE`, `CANDIDATE -> VERIFIED`), batch-persisting assertions and state events into `DurableAssertionStore`, and linking them to the release ID via `release_assertions`.
  - **Stage 6 (Provenance & Lineage)**: Resolves source release IDs, computes artifact digests, and records lineage.
  - **Stage 7 (Validation & Structural Integrity)**: Validates assertions against schema rules and advances the release via `ReleaseManager.complete_validation()`.
  - **Stage 8 (Release Manifest)**: Assembles `ReleaseManifest` with source artifact digests, assertion IDs, and lockfiles, establishing the validated `Release` candidate.
  - **Stage 9 (RDF Snapshot)**: Compiles and serializes an immutable authoritative `RDFDataset` via `RDFReleaseWriter` and registers it in `AuthoritativeReleaseRDFSource`.
  - **Stage 10 (Projection Build & Validation)**: Executes backend-specific `build()` and `validate()`, recording the manifest record in `DurableProjectionStore`.
  - **Stage 11 (Reconciliation)**: Validates projected entity and relation counts against the authoritative RDF dataset via `ProjectionReconciler`.
  - **Stage 12 (Atomic Endpoint Switch)**: Evaluates strict `ReleaseGate`, advances `ReleaseManager` through `approve()` and `publish()`, activates the projection candidate (`ACTIVE`), and updates the release status to `PUBLISHED` in `GraphStore`.
  - **Stage 13 (Non-Destructive Canary Rollback)**: Deploys an isolated canary projection through the full lifecycle (`BUILDING -> VALIDATING -> RECONCILING -> READY -> ACTIVE -> ROLLBACK`), destroys the canary, and verifies that the production projection remains `ACTIVE` and undeactivated.
- **Fail-Closed Release Quarantine**:
  - Injected failures at any stage immediately halt execution, record detailed stage evidence with error details, and transition the release to `QUARANTINED` in both `ReleaseManager` and `GraphStore`.
- **GraphStore Status Updates (`infrastructure/storage/graph_store.py`)**:
  - Added `update_release_status(release_id, status, quarantine_reasons)` supporting atomic lifecycle status updates on existing release records.

Validation:

- `tests/test_13_stage_pipeline_activation.py` (15 tests):
  - Synthetic domain pack end-to-end full execution.
  - Biomedical domain pack end-to-end full execution.
  - Custom raw artifact ingestion and source release linking.
  - Parameterized failure injection across all 12 stages verifying that every stage fails cleanly and marks the release `QUARANTINED`.
- Full repository test suite: **857 passed**, 0 failures, 0 warnings.
- Strict mypy: clean across 234 source files.
- Ruff: clean across the repository.

## 12. Full Projection-Aware Rollback in REST API

### Dual-layer atomic rollback orchestrating graph snapshots and durable projection manifests

Problem:

The REST API endpoint `POST /api/release/rollback` only rolled back SQLite graph snapshots in `GraphStore`. Projections in `DurableProjectionStore` remained in `ACTIVE` status for the rolled-back release, leaving a split-brain state where the raw graph reverted to the previous release while projection manifests and backend endpoints continued serving the discarded release.

Implementation:

- **Server-Level Projection Infrastructure (`infrastructure/api/server.py`)**:
  - Initialized `PROJECTION_STORE = DurableProjectionStore(GRAPH_STORE.database_path)`.
  - Registered `MemoryProjectionBackend` and `RDFProjectionBackend` with `PROJECTION_REGISTRY` tied to `AuthoritativeReleaseRDFSource`.
- **Durable Store Rollback Primitives (`infrastructure/storage/projection_store.py`)**:
  - `get_all_active()`: Queries all currently active projection manifests across backends.
  - `get_previous_projection()`: Resolves the prior projection manifest for a backend, supporting optional explicit `target_release_id`.
  - `rollback_projection()`: Atomically demotes the active projection to `ROLLED_BACK` and promotes the target/previous projection to `ACTIVE` with updated activation timestamp.
- **Upgraded `POST /api/release/rollback`**:
  - Coordinated dual-layer rollback: Rolls back graph nodes/edges via `GRAPH_STORE.rollback()` and projection manifests via `PROJECTION_STORE.rollback_projection()`.
  - Invokes `backend.rollback()` across registered projection backends.
  - Supports optional `target_release_id` in the request body for historical release targeting.
  - Preserves legacy tolerance: If a release has graph snapshots but no projection records (or vice versa), rolls back available layers cleanly.
  - Returns enhanced backward-compatible payload:
    ```json
    {
      "status": "success",
      "rollback": {
        "restored_nodes": 10,
        "restored_edges": 6,
        "durability": "sqlite",
        "active_release_id": "release_prior_001",
        "restored_projections": [...],
        "demoted_projections": [...]
      }
    }
    ```
- **New `GET /api/projections/active` Endpoint**:
  - Exposes all currently active projections, backend IDs, record counts, and release IDs for client and UI inspection.

Validation:

- `tests/test_api_projection_rollback.py` (4 tests):
  - Initial empty state inspection.
  - Pipeline execution activating projections and subsequent rollback restoring prior release projections.
  - Explicit historical `target_release_id` targeting.
  - HTTP 409 `unavailable` when no rollback history exists.
- `tests/test_ui_api.py` (13 tests) passing without regressions.

## 13. Benchmark Integrity and Honest Evaluation

### Replacement of synthetic generator and fabricated multipliers with real versioned datasets, dual-build reproducibility, and genuine operational latencies

Problem:

The benchmarking suite `infrastructure/benchmarking/benchmark.py` suffered from severe integrity defects:
1. It used a small 50-item in-memory synthetic dataset (`http://benchmark.org/src/entity_{i}`) with trivial string matching that bypassed real biomedical ambiguity.
2. Operational metrics were mathematically fabricated using proportional multipliers: `rollback_time_ms = round(reconcile_time_ms * 0.5, 3)` and `endpoint_switch_time_ms = round(reconcile_time_ms * 0.2, 3)`.
3. `rebuild_reproducible` was hardcoded to `True` without ever building or verifying a second projection.
4. Candidate evaluation latency was conflated with projection build and reconciliation timings.

Implementation:

- **Versioned Evaluation Dataset (`data/benchmarks/biomedical_eval_v1.json`)**:
  - Curated 80 real biomedical entities across Genes/Proteins (EGFR, TP53, BRCA1, KRAS, ERBB2, CDK4, etc.), Drugs (Imatinib, Gefitinib, Trastuzumab, Osimertinib, Aspirin, etc.), and Diseases (NSCLC, Breast Neoplasms, Glioblastoma, Type 2 Diabetes, etc.).
  - 60 ground-truth positive pairs across exact cross-source URIs and normalized synonym/alias matches.
  - 20 hard negative pairs (e.g. EGFR vs ERBB2 homologues, CDK4 vs CDK6, Imatinib vs Dasatinib) and disjoint non-matching entities.
  - Accompanied by SHA-256 digest validation (`biomedical_eval_v1.json.sha256`), fail-closed on tampering or corruption.
- **True Projection Lifecycle Operations**:
  - **`build_time_ms`**: Measured directly from `backend.build(manifest)`.
  - **`rebuild_reproducible`**: Evaluated by executing an independent second build on a separate replica backend from the authoritative RDF dataset, computing record digests, and verifying `digest_1 == digest_2`.
  - **`reconciliation_time_ms`**: Measured directly from `ProjectionReconciler().reconcile()` against authoritative RDF.
  - **`endpoint_switch_time_ms`**: Measured directly from `backend.activate()`.
  - **`rollback_time_ms`**: Measured directly from `backend.rollback()`.
  - **Zero Fabricated Multipliers**: Proportional multipliers were completely eliminated.
- **Fail-Closed Threshold Validation Gates**:
  - `BenchmarkIntegrityError` exception.
  - `validate_thresholds()` method and `strict: bool` parameter on `SystemBenchmarker.run_benchmarks()` enforcing minimum Precision, Recall, F1, maximum ECE, maximum Brier score, positive operational latencies, and projection rebuild reproducibility.
- **REST API Endpoint (`GET /api/benchmarks/metrics`)**:
  - Serves live, authentic benchmark evaluation results computed from the versioned dataset.

Validation:

- `tests/test_performance_benchmarks.py` (6 tests):
  - `test_system_benchmarker_records_all_required_metrics`: Validates candidate recall, resolution precision/recall/F1, calibration ECE/Brier, and operational latencies.
  - `test_benchmark_dataset_loading_and_sha256_verification`: Validates SHA-256 verification and checksum tamper rejection.
  - `test_operational_timings_are_authentic_and_not_fabricated_multipliers`: Asserts that operational timings are not proportional multipliers.
  - `test_projection_dual_build_reproducibility`: Asserts dual-build digest equivalence.
  - `test_strict_threshold_validation_gates`: Asserts strict pass and threshold breach detection.
  - `test_validation_gate_detects_non_reproducible_rebuild`: Asserts fail-closed behavior on hash mismatch.
- `tests/test_ui_api.py::test_api_benchmarks_metrics_endpoint`: Integration test for `GET /api/benchmarks/metrics`.
- Full repository test suite: **863 passed**, 0 failures, 0 warnings.
- Strict mypy: clean across 254 source files.
- Ruff: clean across the repository.

## 14. Remaining Production Blockers

The following items are still incomplete and must not be presented as finished:

### Authentication and authorization

The API does not yet enforce authentication or role-based authorization for ingestion, release activation, rollback, or model access.

### Production server and operations

The current server is still the standard-library development HTTP server. Production deployment requires an ASGI/WSGI server, reverse proxy, secrets management, observability, dependency health checks, and restore drills.

## Final Assessment

The repository now has a substantially more reliable fusion core, durable graph and release payload storage, content-addressed artifact and typed assertion stores, canonical real projection execution, full 13-stage release pipeline activation with durable persistence and non-destructive canary rollback, full projection-aware REST API rollback, honest model/API failure behavior, candidate lifecycle records, versioned biomedical benchmark integrity with true dual-build reproducibility and zero fabricated metrics, clean strict typing across 254 source files, repository-wide Ruff compliance, and 863 passing regression tests.

It is **not yet fully production-ready**. The remaining work is concentrated in authentication/authorization and production server deployment.

Current practical rating: **approximately 9.4/10 for engineering readiness**.

Production release decision: **Do not deploy as a production knowledge-graph release platform yet.**


