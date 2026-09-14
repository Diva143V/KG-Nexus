"""SearchProjectionBackend: project an RDF release into a search index.

RDF is authoritative. This backend indexes a release's approved content into
deterministic search documents — entities, relations, and assertions — plus a
manifest recording the search engine id, engine version, engine configuration,
source release, and content digest. The projection provides fast textual
discovery (full-text search, aliases, labels, descriptions, identifiers)
without introducing semantic authority into the search engine.

Search results are retrieval candidates only. Search ranking must not directly
promote assertions: this backend never approves anything, never replaces
IdentityPolicy / EvidencePolicy / validators, and never becomes a semantic
authority. Its records reported to Core are derived from the indexed content
so reconciliation stays meaningful, and its search answers are candidates
with scores — nothing more.

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
from infrastructure.projections.search.builder import (
    SearchDataSource,
    SearchProjectionBuilder,
)
from infrastructure.projections.search.documents import SearchDocument
from infrastructure.projections.search.errors import UnknownSearchProjectionError
from infrastructure.projections.search.index import (
    DefaultTextSearchEngine,
    SearchEngine,
)
from infrastructure.projections.search.manifest import SearchManifest
from infrastructure.projections.search.reconciler import (
    SearchReconciler,
    SearchReconciliationReport,
)
from infrastructure.projections.search.retrieval import (
    SearchResult,
    SearchRetriever,
)
from infrastructure.projections.search.smoke_tests import (
    SearchSmokeTestResult,
    SearchSmokeTestRunner,
)
from infrastructure.projections.search.store import (
    SearchProjectionStore,
    search_candidate_name,
)
from infrastructure.projections.search.writer import (
    try_documents_from_bytes,
    try_manifest_from_bytes,
)


class SearchProjectionBackend:
    """Concrete ProjectionBackend that produces a searchable document index.

    ``data_source`` supplies the authoritative RDF release the backend
    projects. ``store`` is where a real search store (an OpenSearch /
    Elasticsearch cluster, ...) plugs in; tests inject an in-memory store.
    ``engine`` is the search engine boundary where a real engine plugs in.
    """

    def __init__(
        self,
        *,
        store: SearchProjectionStore,
        data_source: SearchDataSource,
        engine: SearchEngine | None = None,
        backend_id: str = "search",
        builder: SearchProjectionBuilder | None = None,
        reconciler: SearchReconciler | None = None,
        smoke_tests: SearchSmokeTestRunner | None = None,
        retriever: SearchRetriever | None = None,
    ) -> None:
        self.backend_id = backend_id
        self._store = store
        self._data_source = data_source
        self._engine = engine or DefaultTextSearchEngine()
        self._builder = builder or SearchProjectionBuilder(
            store=store,
            data_source=data_source,
            engine=self._engine,
        )
        self._reconciler = reconciler or SearchReconciler(
            store=store,
            data_source=data_source,
            builder=self._builder,
        )
        self._smoke_tests = smoke_tests or SearchSmokeTestRunner(
            store=store,
            engine=self._engine,
        )
        self._retriever = retriever or SearchRetriever(index=self._engine.index(()))
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
            message="search projection built",
            record_count=record_count,
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate: structure, reconciliation, and smoke tests.

        A candidate is only valid if it matches the policy-derived expected
        search content exactly and passes smoke tests. Failed candidates are
        reported, never activated.
        """
        release_id, profile = self._require(projection_id)
        store_key = search_candidate_name(projection_id)
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

        Records are derived from the documents actually indexed, so they
        reflect exactly what the search index contains. A faithful projection
        is indistinguishable from the release, and declared transformations
        surface as Core-level "transformed" records.
        """
        self._require(projection_id)
        documents = self._stored_documents(search_candidate_name(projection_id))
        return tuple(
            sorted(
                (
                    ProjectedRecord(
                        kind=document.kind,
                        key=document.doc_id,
                        digest=document.digest,
                    )
                    for document in documents
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
        self._store.activate(search_candidate_name(projection_id))

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection; retained content stays untouched."""
        self._require(projection_id)
        self._store.rollback(search_candidate_name(projection_id))

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection's content, if present."""
        self._store.delete_projection(search_candidate_name(projection_id))
        self._projects.pop(projection_id, None)

    def reconcile(
        self,
        projection_id: str,
    ) -> SearchReconciliationReport:
        """Search-specific reconciliation report for the candidate."""
        release_id, profile = self._require(projection_id)
        return self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )

    def smoke_test(
        self,
        projection_id: str,
    ) -> SearchSmokeTestResult:
        """Smoke test report for the candidate."""
        release_id, profile = self._require(projection_id)
        expected = self._builder.expected(release_id, profile)
        return self._smoke_tests.run(projection_id=projection_id, expected=expected)

    def manifest(
        self,
        projection_id: str,
    ) -> SearchManifest:
        """The manifest recorded with the projection."""
        self._require(projection_id)
        manifest = self._stored_manifest(self._resolve_store_key(projection_id))
        if manifest is None:
            raise UnknownSearchProjectionError(projection_id)
        return manifest

    def documents(
        self,
        projection_id: str,
    ) -> tuple[SearchDocument, ...]:
        """The documents indexed with the projection."""
        self._require(projection_id)
        return self._stored_documents(self._resolve_store_key(projection_id))

    def search(
        self,
        projection_id: str,
        query: str,
        k: int = 5,
    ) -> tuple[SearchResult, ...]:
        """Return the ``k`` most relevant retrieval candidates for ``query``.

        Full-text search covers aliases, labels, descriptions, and
        identifiers. Results are candidates with scores, never approval or
        identity claims.
        """
        self._require(projection_id)
        documents = self._stored_documents(self._resolve_store_key(projection_id))
        index = self._engine.index(documents)
        return SearchRetriever(index=index).search(
            documents=documents,
            query=query,
            k=k,
        )

    def resolve_alias(
        self,
        projection_id: str,
        alias: str,
    ) -> tuple[SearchResult, ...]:
        """Return the documents that carry ``alias``, in deterministic order."""
        self._require(projection_id)
        documents = self._stored_documents(self._resolve_store_key(projection_id))
        index = self._engine.index(documents)
        return SearchRetriever(index=index).resolve_alias(
            documents=documents,
            alias=alias,
        )

    def _structural_errors(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> list[str]:
        expected = self._builder.derive(release_id, profile)
        store_key = search_candidate_name(projection_id)
        errors: list[str] = []

        manifest = self._stored_manifest(store_key)
        if manifest is None:
            errors.append("manifest missing or unreadable")
        elif manifest.record_count != expected.manifest.record_count:
            errors.append("manifest record count mismatch")

        documents = self._stored_documents(store_key)
        if not documents:
            errors.append("documents missing or unreadable")
        return errors

    def _stored_manifest(self, store_key: str) -> SearchManifest | None:
        data = self._store.read_dataset(store_key, "manifest")
        if data is None:
            return None
        return try_manifest_from_bytes(data)

    def _stored_documents(self, store_key: str) -> tuple[SearchDocument, ...]:
        data = self._store.read_dataset(store_key, "documents")
        if data is None:
            return ()
        documents = try_documents_from_bytes(data)
        if documents is None:
            return ()
        return documents

    def _resolve_store_key(self, projection_id: str) -> str:
        active = self._store.active_projection()
        if active is not None:
            return active
        return search_candidate_name(projection_id)

    def _require(self, projection_id: str) -> tuple[str, ProjectionProfile]:
        entry = self._projects.get(projection_id)
        if entry is None:
            raise UnknownSearchProjectionError(projection_id)
        return entry

    @staticmethod
    def _report_summary(report: SearchReconciliationReport) -> str:
        parts = [
            f"missing_documents={len(report.missing_documents)}",
            f"unexpected_documents={len(report.unexpected_documents)}",
            f"transformed_documents={len(report.transformed_documents)}",
            f"manifest_matches={report.manifest_matches}",
        ]
        return ", ".join(parts)


def conforms_to_backend(backend: object) -> bool:
    """True when ``backend`` implements the ProjectionBackend contract."""
    return isinstance(backend, ProjectionBackend)
