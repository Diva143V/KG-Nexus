"""Search projection reconciliation against the authoritative RDF release.

RDF is authoritative. The reconciler compares the stored search projection
against the policy-derived expected projection and reports, in deterministic
string terms:

* missing / unexpected documents;
* transformed documents (same document id, different digest);
* document counts per kind;
* whether the stored manifest matches the expected manifest.

Data loss is never silently accepted: any divergence is reported. Document
comparisons use the stored manifest and documents as they actually landed, so
tampering or corruption surfaces instead of being masked by re-derivation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from infrastructure.projections.search.builder import (
    SearchDataSource,
    SearchProjectionBuilder,
)
from infrastructure.projections.search.manifest import SearchManifest
from infrastructure.projections.search.store import (
    SearchProjectionStore,
    search_candidate_name,
)
from infrastructure.projections.search.writer import (
    manifest_bytes,
    try_documents_from_bytes,
    try_manifest_from_bytes,
)


class SearchReconciliationReport(BaseModel):
    """Outcome of reconciling one search projection against its release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    missing_documents: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_documents: tuple[str, ...] = Field(default_factory=tuple)
    transformed_documents: tuple[str, ...] = Field(default_factory=tuple)
    document_counts: dict[str, int] = Field(default_factory=dict)
    manifest_matches: bool = True

    @property
    def reconciled(self) -> bool:
        """True when the projection matches the expected search content."""
        return (
            not (self.missing_documents or self.unexpected_documents or self.transformed_documents)
            and self.manifest_matches
        )


class SearchReconciler:
    """Reconciles stored documents against the authoritative RDF release."""

    def __init__(
        self,
        *,
        store: SearchProjectionStore,
        data_source: SearchDataSource,
        builder: SearchProjectionBuilder | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._builder = builder or SearchProjectionBuilder(
            store=store,
            data_source=data_source,
        )

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> SearchReconciliationReport:
        """Compare the stored search projection against the expected one."""
        expected = self._builder.derive(release_id, profile)
        store_key = search_candidate_name(projection_id)

        expected_documents = {document.doc_id: document.digest for document in expected.documents}
        actual_documents = self._stored_documents(store_key)

        missing_documents = sorted(expected_documents.keys() - set(actual_documents))
        unexpected_documents = sorted(set(actual_documents) - expected_documents.keys())
        transformed_documents = sorted(
            doc_id
            for doc_id in expected_documents.keys() & set(actual_documents)
            if expected_documents[doc_id] != actual_documents[doc_id]
        )

        stored_manifest = self._stored_manifest(store_key)
        manifest_matches = stored_manifest is not None and manifest_bytes(
            stored_manifest
        ) == manifest_bytes(expected.manifest)

        document_counts: dict[str, int] = {}
        for kind in self._stored_kinds(store_key).values():
            document_counts[kind] = document_counts.get(kind, 0) + 1

        return SearchReconciliationReport(
            projection_id=projection_id,
            release_id=release_id,
            missing_documents=tuple(missing_documents),
            unexpected_documents=tuple(unexpected_documents),
            transformed_documents=tuple(transformed_documents),
            document_counts=document_counts,
            manifest_matches=manifest_matches,
        )

    def _stored_documents(self, store_key: str) -> dict[str, str]:
        data = self._store.read_dataset(store_key, "documents")
        if data is None:
            return {}
        documents = try_documents_from_bytes(data)
        if documents is None:
            return {}
        return {document.doc_id: document.digest for document in documents}

    def _stored_manifest(self, store_key: str) -> SearchManifest | None:
        data = self._store.read_dataset(store_key, "manifest")
        if data is None:
            return None
        return try_manifest_from_bytes(data)

    def _stored_kinds(self, store_key: str) -> dict[str, str]:
        data = self._store.read_dataset(store_key, "documents")
        if data is None:
            return {}
        documents = try_documents_from_bytes(data)
        if documents is None:
            return {}
        return {document.doc_id: document.kind for document in documents}
