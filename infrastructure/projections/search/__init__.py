"""Search projection backend.

A derived discovery layer over an authoritative RDF release: the approved
content becomes deterministic search documents (entities, relations,
assertions) with a manifest recording the search engine id, engine version,
engine configuration, source release, and content digest. The projection
provides fast textual discovery — full-text search, aliases, labels,
descriptions, and identifiers. RDF is authoritative and remains so — search
ranking never establishes identity or truth, and this backend never approves
assertions or replaces any policy or validator. Core never imports this
package; it reaches the backend through the ``ProjectionRegistry``.
"""

from __future__ import annotations

from infrastructure.projections.search.backend import (
    SearchProjectionBackend,
    conforms_to_backend,
)
from infrastructure.projections.search.builder import (
    ExpectedSearchProjection,
    MemorySearchDataSource,
    SearchDataSource,
    SearchProjection,
    SearchProjectionBuilder,
)
from infrastructure.projections.search.documents import (
    ASSERTION,
    ENTITY,
    RELATION,
    SearchDocument,
)
from infrastructure.projections.search.errors import (
    MissingSearchReleaseError,
    SearchClientError,
    SearchIndexError,
    SearchProjectionError,
    SearchReconciliationError,
    SearchSmokeTestError,
    SearchUnsupportedSemanticsError,
    SearchValidationError,
    UnknownSearchProjectionError,
)
from infrastructure.projections.search.index import (
    DEFAULT_ENGINE_ID,
    DEFAULT_ENGINE_VERSION,
    DefaultTextSearchEngine,
    InvertedSearchIndex,
    SearchEngine,
    SearchIndex,
    tokenize,
)
from infrastructure.projections.search.manifest import SearchManifest
from infrastructure.projections.search.policy import (
    SearchProjectionPolicy,
    policy_from_profile,
)
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
    MemorySearchProjectionStore,
    SearchProjectionStore,
    search_candidate_name,
)
from infrastructure.projections.search.writer import (
    content_digest,
    documents_bytes,
    manifest_bytes,
)

__all__ = [
    "ASSERTION",
    "DEFAULT_ENGINE_ID",
    "DEFAULT_ENGINE_VERSION",
    "DefaultTextSearchEngine",
    "ENTITY",
    "ExpectedSearchProjection",
    "InvertedSearchIndex",
    "MemorySearchDataSource",
    "MemorySearchProjectionStore",
    "MissingSearchReleaseError",
    "RELATION",
    "SearchClientError",
    "SearchDataSource",
    "SearchDocument",
    "SearchEngine",
    "SearchIndex",
    "SearchIndexError",
    "SearchManifest",
    "SearchProjection",
    "SearchProjectionBackend",
    "SearchProjectionBuilder",
    "SearchProjectionError",
    "SearchProjectionPolicy",
    "SearchProjectionStore",
    "SearchReconciler",
    "SearchReconciliationError",
    "SearchReconciliationReport",
    "SearchResult",
    "SearchRetriever",
    "SearchSmokeTestError",
    "SearchSmokeTestResult",
    "SearchSmokeTestRunner",
    "SearchUnsupportedSemanticsError",
    "SearchValidationError",
    "UnknownSearchProjectionError",
    "conforms_to_backend",
    "content_digest",
    "documents_bytes",
    "manifest_bytes",
    "policy_from_profile",
    "search_candidate_name",
    "tokenize",
]
