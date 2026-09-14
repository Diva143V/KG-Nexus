"""Vector projection backend.

A derived retrieval layer over an authoritative RDF release: the approved
content is embedded into deterministic vectors (entities, relations,
assertions) with a manifest recording the embedding model id, model version,
embedding configuration, source release, and embedding digest. The projection
is used for candidate retrieval, semantic search, similarity search, and
retrieval augmentation. RDF is authoritative and remains so — vector
similarity never establishes identity or truth, and this backend never
approves assertions or replaces any policy or validator. Core never imports
this package; it reaches the backend through the ``ProjectionRegistry``.
"""

from __future__ import annotations

from infrastructure.projections.vector.backend import (
    VectorProjectionBackend,
    conforms_to_backend,
)
from infrastructure.projections.vector.builder import (
    ExpectedVectorProjection,
    MemoryVectorDataSource,
    VectorDataSource,
    VectorProjection,
    VectorProjectionBuilder,
)
from infrastructure.projections.vector.embedder import (
    DEFAULT_DIMENSIONS,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_VERSION,
    DeterministicHashEmbedder,
    EmbeddingModel,
)
from infrastructure.projections.vector.errors import (
    MissingVectorReleaseError,
    UnknownVectorProjectionError,
    VectorClientError,
    VectorIndexError,
    VectorProjectionError,
    VectorReconciliationError,
    VectorSmokeTestError,
    VectorUnsupportedSemanticsError,
    VectorValidationError,
)
from infrastructure.projections.vector.index import (
    BruteForceVectorIndex,
    VectorIndex,
    VectorIndexEntry,
)
from infrastructure.projections.vector.manifest import VectorManifest
from infrastructure.projections.vector.models import EmbeddedItem
from infrastructure.projections.vector.policy import (
    VectorProjectionPolicy,
    policy_from_profile,
)
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
    MemoryVectorProjectionStore,
    VectorProjectionStore,
    vector_candidate_name,
)
from infrastructure.projections.vector.writer import (
    embedding_digest,
    items_bytes,
    manifest_bytes,
)

__all__ = [
    "BruteForceVectorIndex",
    "DEFAULT_DIMENSIONS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_MODEL_VERSION",
    "DeterministicHashEmbedder",
    "EmbeddedItem",
    "EmbeddingModel",
    "ExpectedVectorProjection",
    "MemoryVectorDataSource",
    "MemoryVectorProjectionStore",
    "MissingVectorReleaseError",
    "UnknownVectorProjectionError",
    "VectorClientError",
    "VectorDataSource",
    "VectorIndex",
    "VectorIndexEntry",
    "VectorIndexError",
    "VectorManifest",
    "VectorProjection",
    "VectorProjectionBackend",
    "VectorProjectionBuilder",
    "VectorProjectionError",
    "VectorProjectionPolicy",
    "VectorProjectionStore",
    "VectorReconciler",
    "VectorReconciliationError",
    "VectorReconciliationReport",
    "VectorRetriever",
    "VectorSearchResult",
    "VectorSmokeTestError",
    "VectorSmokeTestResult",
    "VectorSmokeTestRunner",
    "VectorUnsupportedSemanticsError",
    "VectorValidationError",
    "conforms_to_backend",
    "embedding_digest",
    "items_bytes",
    "manifest_bytes",
    "policy_from_profile",
    "vector_candidate_name",
]
