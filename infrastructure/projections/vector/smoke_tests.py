"""Vector projection smoke tests.

Smoke tests spot-check that the embedded content is usable where it landed:
the manifest is readable and self-consistent, the vectors parse back, the item
count matches the expected content, the embeddings are reproducible from their
surfaces (the "deterministic, rebuildable from RDF" guarantee), and similarity
retrieval answers queries. They are deterministic and do not depend on the
shape of any particular release. Retrieval being queryable never changes the
authoritative RDF.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.vector.builder import ExpectedVectorProjection
from infrastructure.projections.vector.embedder import EmbeddingModel
from infrastructure.projections.vector.index import (
    BruteForceVectorIndex,
    VectorIndexEntry,
)
from infrastructure.projections.vector.models import EmbeddedItem
from infrastructure.projections.vector.store import (
    VectorProjectionStore,
    vector_candidate_name,
)
from infrastructure.projections.vector.writer import (
    try_items_from_bytes,
    try_manifest_from_bytes,
)

_SEARCH_TOLERANCE = 1e-9


class VectorSmokeTestResult(BaseModel):
    """Outcome of the smoke tests for one vector projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_readable: bool = False
    vectors_readable: bool = False
    counts_match: bool = False
    embeddings_deterministic: bool = False
    retrieval_queryable: bool = False
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every smoke check succeeded."""
        return (
            self.manifest_readable
            and self.vectors_readable
            and self.counts_match
            and self.embeddings_deterministic
            and self.retrieval_queryable
            and not self.errors
        )


class VectorSmokeTestRunner:
    """Runs deterministic smoke tests against the stored vector projection."""

    def __init__(
        self,
        *,
        store: VectorProjectionStore,
        embedder: EmbeddingModel,
    ) -> None:
        self._store = store
        self._embedder = embedder

    def run(
        self,
        *,
        projection_id: str,
        expected: ExpectedVectorProjection,
    ) -> VectorSmokeTestResult:
        """Run the smoke tests for the projection under ``projection_id``."""
        store_key = vector_candidate_name(projection_id)
        if not self._store.has_projection(store_key):
            return VectorSmokeTestResult(errors=("no candidate projection",))

        manifest_data = self._store.read_dataset(store_key, "manifest")
        manifest = try_manifest_from_bytes(manifest_data) if manifest_data is not None else None
        manifest_readable = (
            manifest is not None
            and manifest.model_id == self._embedder.model_id
            and manifest.model_version == self._embedder.model_version
            and manifest.dimensions == self._embedder.dimensions
            and manifest.record_count == expected.item_count
        )

        vectors_data = self._store.read_dataset(store_key, "vectors")
        items = try_items_from_bytes(vectors_data) if vectors_data is not None else None
        vectors_readable = items is not None
        items = items or ()
        counts_match = len(items) == expected.item_count

        embeddings_deterministic = all(
            self._embedder.embed(item.text) == item.vector for item in items
        )
        retrieval_queryable = self._retrieval_queryable(items)

        errors: list[str] = []
        if not manifest_readable:
            errors.append("manifest is not readable or does not match the model")
        if not vectors_readable:
            errors.append("vectors are not readable")
        if not counts_match:
            errors.append("vector count does not match the expected content")
        if not embeddings_deterministic:
            errors.append("embeddings are not reproducible from their surfaces")
        if not retrieval_queryable:
            errors.append("similarity retrieval failed")

        return VectorSmokeTestResult(
            manifest_readable=manifest_readable,
            vectors_readable=vectors_readable,
            counts_match=counts_match,
            embeddings_deterministic=embeddings_deterministic,
            retrieval_queryable=retrieval_queryable,
            errors=tuple(errors),
        )

    def _retrieval_queryable(self, items: tuple[EmbeddedItem, ...]) -> bool:
        if not items:
            return True
        first = items[0]
        query = self._embedder.embed(first.text)
        index = BruteForceVectorIndex(
            tuple(VectorIndexEntry(key=item.key, vector=item.vector) for item in items)
        )
        hits = index.search(query, 1)
        if len(hits) != 1:
            return False
        _key, score = hits[0]
        return 1.0 - _SEARCH_TOLERANCE <= score <= 1.0 + _SEARCH_TOLERANCE
