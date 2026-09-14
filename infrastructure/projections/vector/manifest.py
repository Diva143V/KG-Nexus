"""Vector projection manifest.

The manifest records the provenance and provenance-related metadata of a
vector projection: which embedding model and version produced the vectors,
what embedding configuration was used, which authoritative release the
vectors were derived from, and the embedding digest that makes the projection
verifiable. The manifest is deliberately deterministic — it never records a
wall-clock timestamp — so identical RDF releases produce identical manifests.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VectorManifest(BaseModel):
    """Metadata recorded with a vector projection.

    ``record_count`` is the number of embedded items and ``embedding_digest``
    is a stable digest over the exact vector content, so a projection can be
    verified against its manifest and rebuilt deterministically from RDF.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    dimensions: int = Field(ge=1)
    embedding_config: dict[str, object] = Field(default_factory=dict)
    release_id: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    embedding_digest: str = Field(min_length=1)
