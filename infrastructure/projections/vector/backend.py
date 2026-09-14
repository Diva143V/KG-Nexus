"""VectorProjectionBackend: project an RDF release into a vector index.

RDF is authoritative. This backend embeds a release's approved content into
deterministic vectors — entities, relations, and assertions — plus a manifest
recording the embedding model id, model version, embedding configuration,
source release, and embedding digest. The projection is a retrieval/indexing
layer for candidate retrieval, semantic search, similarity search, and
retrieval augmentation.

Vector similarity MUST NOT establish identity. This backend never approves
assertions, never replaces IdentityPolicy / EvidencePolicy / validators, and
never becomes a semantic authority. Its records reported to Core are derived
from the embedded content so reconciliation stays meaningful, and its
retrieval answers are candidates with scores — nothing more.

It implements the Phase 13 ``ProjectionBackend`` contract and is registered
through ``ProjectionRegistry``; Core never imports it and never knows its
store.

Lifecycle within the backend:

    BUILD (candidate) -> VALIDATE -> RECONCILE -> SMOKE TEST -> READY

Activation is atomic: the candidate is promoted to active while the previous
active projection is retained for rollback (its content is never deleted
before activation).
"""

from __future__ import annotations

from core.projection.backend import ProjectionBackend
from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import ProjectedRecord
from core.projection.result import ProjectionResult, ProjectionValidationResult
from infrastructure.projections.vector.builder import (
    VectorDataSource,
    VectorProjectionBuilder,
)
from infrastructure.projections.vector.embedder import (
    DEFAULT_DIMENSIONS,
    DeterministicHashEmbedder,
    EmbeddingModel,
)
from infrastructure.projections.vector.errors import UnknownVectorProjectionError
from infrastructure.projections.vector.manifest import VectorManifest
from infrastructure.projections.vector.models import EmbeddedItem
from infrastructure.projections.vector.reconciler import (
    VectorReconciler,
    VectorReconciliationReport,
)
from infrastructure.projections.vector.retrieval import (
    VectorRetriever,
    VectorSearchResult,
)
from infrastructure.projections.vector.smoke_tests import (
    VectorSmokeTestResult,
    VectorSmokeTestRunner,
)
from infrastructure.projections.vector.store import (
    VectorProjectionStore,
    vector_candidate_name,
)
from infrastructure.projections.vector.writer import (
    try_items_from_bytes,
    try_manifest_from_bytes,
)


class VectorProjectionBackend:
    """Concrete ProjectionBackend that produces a retrieval vector index.

    ``data_source`` supplies the authoritative RDF release the backend
    projects. ``store`` is where a real vector store (FAISS, HNSW, a SQL
    vector index, ...) plugs in; tests inject an in-memory store.
    ``embedder`` is the embedding model boundary where a real semantic
    encoder plugs in.
    """

    def __init__(
        self,
        *,
        store: VectorProjectionStore,
        data_source: VectorDataSource,
        embedder: EmbeddingModel | None = None,
        backend_id: str = "vector",
        builder: VectorProjectionBuilder | None = None,
        reconciler: VectorReconciler | None = None,
        smoke_tests: VectorSmokeTestRunner | None = None,
        retriever: VectorRetriever | None = None,
    ) -> None:
        self.backend_id = backend_id
        self._store = store
        self._data_source = data_source
        self._embedder = embedder or DeterministicHashEmbedder(dimensions=DEFAULT_DIMENSIONS)
        self._builder = builder or VectorProjectionBuilder(
            store=store,
            data_source=data_source,
            embedder=self._embedder,
        )
        self._reconciler = reconciler or VectorReconciler(
            store=store,
            data_source=data_source,
            builder=self._builder,
        )
        self._smoke_tests = smoke_tests or VectorSmokeTestRunner(
            store=store,
            embedder=self._embedder,
        )
        self._retriever = retriever or VectorRetriever(embedder=self._embedder)
        self._projects: dict[str, tuple[str, ProjectionProfile]] = {}

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        """Build a candidate projection from the authoritative RDF release."""
        record_count = self._builder.build(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        self._projects[projection_id] = (release_id, profile)
        return ProjectionResult(
            projection_id=projection_id,
            backend_id=self.backend_id,
            message="vector projection built",
            record_count=record_count,
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate: structure, reconciliation, and smoke tests.

        A candidate is only valid if it matches the policy-derived expected
        vector content exactly and passes smoke tests. Failed candidates are
        reported, never activated.
        """
        release_id, profile = self._require(projection_id)
        store_key = vector_candidate_name(projection_id)
        if not self._store.has_projection(store_key):
            return ProjectionValidationResult(
                projection_id=projection_id,
                passed=False,
                errors=("no candidate projection",),
            )

        errors: list[str] = []
        structural = self._structural_errors(projection_id, release_id, profile)
        errors.extend(structural)

        report = self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        if not report.reconciled:
            errors.append(f"reconciliation: {self._report_summary(report)}")

        expected = self._builder.expected(release_id, profile)
        smoke = self._smoke_tests.run(projection_id=projection_id, expected=expected)
        if not smoke.passed:
            errors.append(f"smoke tests: {'; '.join(smoke.errors)}")

        return ProjectionValidationResult(
            projection_id=projection_id,
            passed=not errors,
            errors=tuple(errors),
        )

    def records(
        self,
        projection_id: str,
    ) -> tuple[ProjectedRecord, ...]:
        """Backend-neutral records for the candidate, in Core's canonical form.

        Records are derived from the embedded items actually stored, so they
        reflect exactly what the index contains. A faithful projection is
        indistinguishable from the release, and declared transformations
        surface as Core-level "transformed" records.
        """
        self._require(projection_id)
        items = self._stored_items(vector_candidate_name(projection_id))
        return tuple(
            sorted(
                (
                    ProjectedRecord(
                        kind=item.kind,
                        key=item.key,
                        digest=item.digest,
                    )
                    for item in items
                ),
                key=lambda record: (record.kind, record.key),
            )
        )

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Atomically promote the candidate to active."""
        self._require(projection_id)
        self._store.activate(vector_candidate_name(projection_id))

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection; retained content stays untouched."""
        self._require(projection_id)
        self._store.rollback(vector_candidate_name(projection_id))

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection's content, if present."""
        self._store.delete_projection(vector_candidate_name(projection_id))
        self._projects.pop(projection_id, None)

    def reconcile(
        self,
        projection_id: str,
    ) -> VectorReconciliationReport:
        """Vector-specific reconciliation report for the candidate."""
        release_id, profile = self._require(projection_id)
        return self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )

    def smoke_test(
        self,
        projection_id: str,
    ) -> VectorSmokeTestResult:
        """Smoke test report for the candidate."""
        release_id, profile = self._require(projection_id)
        expected = self._builder.expected(release_id, profile)
        return self._smoke_tests.run(projection_id=projection_id, expected=expected)

    def manifest(
        self,
        projection_id: str,
    ) -> VectorManifest:
        """The manifest recorded with the projection."""
        self._require(projection_id)
        manifest = self._stored_manifest(self._resolve_store_key(projection_id))
        if manifest is None:
            raise UnknownVectorProjectionError(projection_id)
        return manifest

    def items(
        self,
        projection_id: str,
    ) -> tuple[EmbeddedItem, ...]:
        """The embedded items stored with the projection."""
        self._require(projection_id)
        return self._stored_items(self._resolve_store_key(projection_id))

    def search(
        self,
        projection_id: str,
        query: str,
        k: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Return the ``k`` closest retrieval candidates for ``query``.

        Retrieval is candidate retrieval only: results carry similarity scores
        and metadata, never state, identity, or approval.
        """
        self._require(projection_id)
        items = self._stored_items(self._resolve_store_key(projection_id))
        return self._retriever.search(items=items, query=query, k=k)

    def similar(
        self,
        projection_id: str,
        key: str,
        k: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Return the vectors most similar to the item identified by ``key``."""
        self._require(projection_id)
        items = self._stored_items(self._resolve_store_key(projection_id))
        return self._retriever.similar(items=items, key=key, k=k)

    def _structural_errors(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> list[str]:
        expected = self._builder.derive(release_id, profile)
        store_key = vector_candidate_name(projection_id)
        errors: list[str] = []

        manifest = self._stored_manifest(store_key)
        if manifest is None:
            errors.append("manifest missing or unreadable")
        elif manifest.dimensions != expected.manifest.dimensions:
            errors.append("manifest dimension mismatch")
        elif manifest.record_count != expected.manifest.record_count:
            errors.append("manifest record count mismatch")

        items = self._stored_items(store_key)
        if not items:
            errors.append("vectors missing or unreadable")
        return errors

    def _stored_manifest(self, store_key: str) -> VectorManifest | None:
        data = self._store.read_dataset(store_key, "manifest")
        if data is None:
            return None
        return try_manifest_from_bytes(data)

    def _stored_items(self, store_key: str) -> tuple[EmbeddedItem, ...]:
        data = self._store.read_dataset(store_key, "vectors")
        if data is None:
            return ()
        items = try_items_from_bytes(data)
        if items is None:
            return ()
        return items

    def _resolve_store_key(self, projection_id: str) -> str:
        active = self._store.active_projection()
        if active is not None:
            return active
        return vector_candidate_name(projection_id)

    def _require(self, projection_id: str) -> tuple[str, ProjectionProfile]:
        entry = self._projects.get(projection_id)
        if entry is None:
            raise UnknownVectorProjectionError(projection_id)
        return entry

    @staticmethod
    def _report_summary(report: VectorReconciliationReport) -> str:
        parts = [
            f"missing_items={len(report.missing_items)}",
            f"unexpected_items={len(report.unexpected_items)}",
            f"transformed_items={len(report.transformed_items)}",
            f"manifest_matches={report.manifest_matches}",
        ]
        return ", ".join(parts)


def conforms_to_backend(backend: object) -> bool:
    """True when ``backend`` implements the ProjectionBackend contract."""
    return isinstance(backend, ProjectionBackend)
