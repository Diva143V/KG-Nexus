# Production Readiness Implementation Plan

## Current Baseline

Completed work is documented in [`report.md`](file:///d:/Hybrid%20kg/report.md) and [`walkthrough.md`](file:///C:/Users/Diwa/.gemini/antigravity-ide/brain/eb6c7798-524b-47da-8f0c-5fc53d0a93e9/walkthrough.md).

Verified completed baseline:

- **Fusion Correctness & Literal Preservation**: Relational and literal assertions survive normalization, meaning alignment, and canonicalization. Attribute mappings and class lookups are active and configurable.
- **Parser Registry Dispatch & Format Validation**: Active format registry dispatching for JSON-LD, RDF Turtle, and CSV.
- **Durable Multi-Layer Persistence**:
  - `DurableArtifactStore`: Content-addressed SHA-256 storage for raw source payloads and synthesized documents.
  - `DurableAssertionStore`: Typed SQLite persistence with append-only `AssertionStateEvent` transitions.
  - `GraphStore`: SQLite snapshots for raw graph nodes, edges, and fusion release payloads.
  - `DurableProjectionStore`: SQLite projection manifests and status tracking (migrations 001 through 004).
  - ACID backup and restore drills verified in `tests/test_backup_restore.py`.
- **Pluggable Semantic Embeddings**: Pluggable provider architecture (`OllamaEmbeddingProvider`, `HuggingFaceEmbeddingProvider`, `TestDoubleEmbeddingProvider`) with fail-closed availability contract and semantic similarity candidate ranking (`tests/test_embedding_providers.py`).
- **Canonical Projection Architecture**: Standardized canonical `ProjectionBackend(Protocol)` in `contracts/projections.py`, upgraded `MemoryProjectionBackend` with candidate, active, and retained states, and `AuthoritativeReleaseRDFSource` snapshot compiler.
- **Full 13-Stage Release Pipeline Activation**: All 13 stages execute real production services backed by durable stores, enforce strict `ReleaseGate`, execute non-destructive canary rollback in stage 13, and fail-closed quarantine on injected errors (`tests/test_13_stage_pipeline_activation.py`).
- **Full Projection-Aware Rollback in REST API**: Coordinated dual-layer rollback in `POST /api/release/rollback` restoring graph snapshots and projection manifests across registered backends, plus `GET /api/projections/active` (`tests/test_api_projection_rollback.py`).
- **Benchmark Integrity and Honest Evaluation**: Curated versioned biomedical evaluation benchmark dataset (`data/benchmarks/biomedical_eval_v1.json`) with SHA-256 verification, real dual-build projection reproducibility, zero fabricated multipliers, and fail-closed validation gates (`tests/test_performance_benchmarks.py`).
- **Repository Tests**: **863 passed**, 0 failures, 0 warnings.
- **Strict Mypy**: **Clean** across all 254 source files (`mypy --strict core infrastructure sdk plugins`).
- **Ruff**: **Clean** and formatted repository-wide.

This document outlines the remaining roadmap required before production deployment. `audit1.md` is excluded as an immutable historical record.

---

## Completed Production Milestones

### Milestone 1: Core Fusion Correctness & Literal Preservation [COMPLETED]
- Status: **COMPLETED** (Verified by `tests/test_fusion_critical_bugfixes.py` and `tests/test_fusion_stage1_normalization.py`).
- Carried typed literal assertions through normalization, alignment, canonicalization, and projection.
- Fixed class mapping lookup keys and enabled attribute alignment.
- Configured candidate scoring weights (`exact_id_weight`, `label_similarity_weight`, `structural_similarity_weight`, `embedding_weight`) now drive composite scoring.

### Milestone 2: Durable Multi-Layer Persistence [COMPLETED]
- Status: **COMPLETED** (Verified by `tests/test_durable_artifact_store.py`, `tests/test_durable_assertion_store.py`, `tests/test_backup_restore.py`).
- Content-addressed SHA-256 artifact storage (`DurableArtifactStore`).
- Typed SQLite assertion storage with append-only state events (`DurableAssertionStore`).
- SQLite graph snapshots and fusion releases (`GraphStore`).
- Migration scripts 001–004 and ACID backup/restore tooling.

### Milestone 3: Pluggable Semantic Embeddings [COMPLETED]
- Status: **COMPLETED** (Verified by `tests/test_embedding_providers.py`, `tests/test_candidate_finder_embeddings.py`).
- Pluggable provider architecture supporting Ollama, HuggingFace, and test doubles.
- Replaced lexical character-similarity mock with real semantic cosine similarity.
- Fail-closed contract: Unavailable providers produce explicit error/unavailable states rather than silent degradation.

### Milestone 4: Canonical Projection Execution [COMPLETED]
- Status: **COMPLETED** (Verified by `tests/test_projection_execution.py`, `tests/test_projection_framework.py`).
- Standardized `ProjectionBackend(Protocol)` with `build`, `validate`, `records`, `activate`, `rollback`, `destroy`.
- Upgraded `MemoryProjectionBackend` with candidate, active, and retained states.
- Authoritative RDF snapshot compiler (`AuthoritativeReleaseRDFSource`) querying `AssertionStore` by release ID.
- `DurableProjectionStore` tracking projection manifests, status, record counts, and activation timestamps.

### Milestone 5: Full 13-Stage Release Pipeline Activation [COMPLETED]
- Status: **COMPLETED** (Verified with 15 tests in `tests/test_13_stage_pipeline_activation.py`).
- Replaced all mock/generated stages 1–8 with real production services:
  - Stage 1 (Artifact Ingestion), Stage 2 (Record Normalization), Stage 3 (Candidate Generation), Stage 4 (Assertion Creation), Stage 5 (State Transitions), Stage 6 (Provenance & Lineage), Stage 7 (Validation Gate), Stage 8 (Release Manifest), Stage 9 (RDF Snapshot), Stage 10 (Projection Build & Validation), Stage 11 (Reconciliation), Stage 12 (Endpoint Switch), Stage 13 (Non-Destructive Canary Rollback).
- Strict `ReleaseGate` enforcement and fail-closed quarantine marking releases `QUARANTINED` upon error injection.

### Milestone 6: Full Projection-Aware REST API Rollback [COMPLETED]
- Status: **COMPLETED** (Verified with 4 tests in `tests/test_api_projection_rollback.py` and 13 tests in `tests/test_ui_api.py`).
- Coordinated dual-layer rollback in `POST /api/release/rollback`: restores graph snapshots in `GraphStore` and atomically demotes/promotes projection manifests in `DurableProjectionStore`.
- Invokes `backend.rollback()` across registered projection backends.
- New `GET /api/projections/active` endpoint exposing live projection states.

### Milestone 7: Benchmark Integrity and Honest Evaluation [COMPLETED]
- Status: **COMPLETED** (Verified with 6 tests in `tests/test_performance_benchmarks.py` and API test in `tests/test_ui_api.py`).
- Created versioned biomedical evaluation dataset `data/benchmarks/biomedical_eval_v1.json` with 80 real biomedical entities (Genes, Drugs, Diseases), 60 ground-truth pairs, 20 hard negative / disjoint pairs, and companion SHA-256 verification.
- Replaced fabricated proportional multipliers (`* 0.5` and `* 0.2`) with genuine measured wall-clock latencies.
- Evaluated `rebuild_reproducible` via independent dual-build SHA-256 digest comparison.
- Implemented fail-closed threshold validation gates with `BenchmarkIntegrityError`.

---

## Remaining Production Blockers

The following two items are the remaining blockers before full production deployment:

### 1. Authentication and Role-Based Authorization
**Priority**: CRITICAL  
**Effort**: Large  

The REST API currently operates in open development mode without access control for graph mutation, release activation, projection rollback, or model access.

#### Implementation Tasks:
1. **Authentication Layer**:
   - Add token-based authentication (e.g. Bearer API keys / JWT tokens) for all non-public endpoints.
   - Support environment-configured secret keys and key rotation.
2. **Role-Based Access Control (RBAC)**:
   - Define formal authorization roles:
     - `ADMIN`: Full access (release publishing, rollback, schema updates, user management).
     - `OPERATOR`: Ingestion, fusion merge, candidate review, benchmark execution.
     - `READER`: Read-only queries, projection lookups, graph exploration, health checks.
   - Enforce permission checks across `POST /api/graph/merge`, `POST /api/release/rollback`, `POST /api/ingest`, and `POST /api/projections/*`.
3. **Security Invariants & Audit Logging**:
   - Replay protection, token expiry validation, and constant-time token comparison.
   - Audit logging for all denied (401/403) and privileged (200) actions.
   - Restrict CORS headers to configured production origins (disallowing wildcard in production).
4. **Automated Verification**:
   - Security test suite covering anonymous requests, invalid tokens, expired tokens, insufficient role permissions, and successful authorized flows.

**Primary Files**:
- `infrastructure/api/server.py`
- `infrastructure/security/` (new module: `auth.py`, `rbac.py`, `tokens.py`)
- `core/config.py`
- `tests/test_security_auth.py` (new)

---

### 2. Production Server Deployment and Operational Hardening
**Priority**: HIGH  
**Effort**: Medium to Large  

The API server currently uses Python's standard-library `http.server.HTTPServer`, which is single-threaded or basic threading suited for local development, but not an enterprise-grade ASGI/WSGI deployment architecture.

#### Implementation Tasks:
1. **Production ASGI/WSGI Serving Architecture**:
   - Wrap or adapt the API endpoints to an ASGI framework (e.g. FastAPI / Starlette / ASGI adapter) or WSGI framework deployed under `Uvicorn` / `Gunicorn`.
   - Multi-worker process model with graceful shutdown handling (completing in-flight releases before worker termination).
2. **Reverse Proxy & TLS Configuration**:
   - Provide reference Nginx / Caddy reverse proxy configuration templates with TLS termination, rate limiting, and request size caps.
3. **Observability & Health Probes**:
   - Structured JSON logging with correlation IDs (`request_id`, `release_id`, `trace_id`).
   - Standardized Kubernetes health probes:
     - `/livez`: Liveness probe (process responsive).
     - `/readyz`: Readiness probe (SQLite stores accessible, required models/projections initialized).
   - Metrics endpoint (Prometheus format) reporting request count, latency percentiles, active releases, and projection health.
4. **Secrets & Configuration Management**:
   - Environment-based configuration with validation (e.g. `Pydantic-Settings`).
   - Zero hardcoded fallback credentials or development bypasses in production mode.
5. **Operational Drills & Disaster Recovery Runbooks**:
   - Documented and automated disaster recovery restore drills from SQLite backup snapshots.
   - Database migration verification script verifying schema integrity against `migrations/`.

**Primary Files**:
- `infrastructure/api/server.py`
- `infrastructure/api/asgi.py` (new)
- `observability/` (new/enhanced: `logging.py`, `metrics.py`, `probes.py`)
- `deploy/` (new: `Dockerfile`, `docker-compose.yml`, `nginx.conf`)
- `tests/test_production_serving.py` (new)

---

## Production Definition of Done

The platform is officially ready for production release when:

1. **Deterministic Core Invariants**: Assertions are immutable, state transitions are append-only, RDF is authoritative, and projections are derived and rebuildable.
2. **Persistence Guarantee**: All published releases, artifacts, assertions, graph snapshots, and projection manifests are persisted in durable storage and recoverable after cold restart.
3. **Fail-Closed Execution**: Injected failures at any release stage prevent activation and quarantine the candidate.
4. **Honest Evaluation & AI**: Zero fabricated metrics, zero simulated multipliers, versioned evaluation benchmark datasets, and fail-safe `ABSTAIN` on model failures.
5. **Access Control**: Every state-changing API request requires authenticated, authorized credentials with RBAC enforcement.
6. **Enterprise Serving**: Multi-worker ASGI/WSGI serving with reverse proxy, health probes, structured observability, and zero hardcoded secrets.
7. **Quality Gates**: 100% passing test suite, strict mypy typing across all source files, and repository-wide Ruff compliance.
