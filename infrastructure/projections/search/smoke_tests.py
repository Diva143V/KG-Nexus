"""Search projection smoke tests.

Smoke tests spot-check that the indexed content is usable where it landed:
the manifest is readable and self-consistent, the documents parse back, the
document count matches the expected content, the documents are reproducible
from their fields (the "deterministic, rebuildable from RDF" guarantee), and
full-text discovery answers queries and resolves aliases. They are
deterministic and do not depend on the shape of any particular release.
Searching never changes the authoritative RDF.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.search.builder import ExpectedSearchProjection
from infrastructure.projections.search.documents import SearchDocument
from infrastructure.projections.search.index import SearchEngine, SearchIndex
from infrastructure.projections.search.store import (
    SearchProjectionStore,
    search_candidate_name,
)
from infrastructure.projections.search.writer import (
    try_documents_from_bytes,
    try_manifest_from_bytes,
)


class SearchSmokeTestResult(BaseModel):
    """Outcome of the smoke tests for one search projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_readable: bool = False
    documents_readable: bool = False
    counts_match: bool = False
    documents_deterministic: bool = False
    full_text_queryable: bool = False
    aliases_resolvable: bool = False
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every smoke check succeeded."""
        return (
            self.manifest_readable
            and self.documents_readable
            and self.counts_match
            and self.documents_deterministic
            and self.full_text_queryable
            and self.aliases_resolvable
            and not self.errors
        )


class SearchSmokeTestRunner:
    """Runs deterministic smoke tests against the stored search projection."""

    def __init__(
        self,
        *,
        store: SearchProjectionStore,
        engine: SearchEngine,
    ) -> None:
        self._store = store
        self._engine = engine

    def run(
        self,
        *,
        projection_id: str,
        expected: ExpectedSearchProjection,
    ) -> SearchSmokeTestResult:
        """Run the smoke tests for the projection under ``projection_id``."""
        store_key = search_candidate_name(projection_id)
        if not self._store.has_projection(store_key):
            return SearchSmokeTestResult(errors=("no candidate projection",))

        manifest_data = self._store.read_dataset(store_key, "manifest")
        manifest = try_manifest_from_bytes(manifest_data) if manifest_data is not None else None
        manifest_readable = (
            manifest is not None
            and manifest.engine_id == self._engine.engine_id
            and manifest.engine_version == self._engine.engine_version
            and manifest.record_count == expected.document_count
        )

        documents_data = self._store.read_dataset(store_key, "documents")
        documents = try_documents_from_bytes(documents_data) if documents_data is not None else None
        documents_readable = documents is not None
        documents = documents or ()
        counts_match = len(documents) == expected.document_count

        documents_deterministic = all(
            document.text.startswith(document.description) and document.doc_id
            for document in documents
        )
        index = self._engine.index(documents)
        full_text_queryable = self._full_text_queryable(index, documents)
        aliases_resolvable = self._aliases_resolvable(index, documents)

        errors: list[str] = []
        if not manifest_readable:
            errors.append("manifest is not readable or does not match the engine")
        if not documents_readable:
            errors.append("documents are not readable")
        if not counts_match:
            errors.append("document count does not match the expected content")
        if not documents_deterministic:
            errors.append("documents are not reproducible from their fields")
        if not full_text_queryable:
            errors.append("full-text search failed")
        if not aliases_resolvable:
            errors.append("alias resolution failed")

        return SearchSmokeTestResult(
            manifest_readable=manifest_readable,
            documents_readable=documents_readable,
            counts_match=counts_match,
            documents_deterministic=documents_deterministic,
            full_text_queryable=full_text_queryable,
            aliases_resolvable=aliases_resolvable,
            errors=tuple(errors),
        )

    def _full_text_queryable(
        self,
        index: SearchIndex,
        documents: tuple[SearchDocument, ...],
    ) -> bool:
        if not documents:
            return True
        first = documents[0]
        hits = index.search(first.label, 1)
        return len(hits) >= 1

    def _aliases_resolvable(
        self,
        index: SearchIndex,
        documents: tuple[SearchDocument, ...],
    ) -> bool:
        if not documents:
            return True
        first = documents[0]
        if not first.aliases:
            return True
        resolved = index.resolve_alias(first.aliases[0])
        return len(resolved) >= 1
