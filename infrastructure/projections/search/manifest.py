"""Search projection manifest.

The manifest records the provenance of a search projection: which search
engine id and version produced it, what indexing configuration was used,
which authoritative release the documents were derived from, and a content
digest that makes the projection verifiable. The manifest is deliberately
deterministic — it never records a wall-clock timestamp — so identical RDF
releases produce identical manifests and are rebuildable from RDF.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchManifest(BaseModel):
    """Metadata recorded with a search projection.

    ``record_count`` is the number of indexed documents and ``content_digest``
    is a stable digest over the exact document content, so a projection can be
    verified against its manifest and rebuilt deterministically from RDF.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_id: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    engine_config: dict[str, object] = Field(default_factory=dict)
    release_id: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    content_digest: str = Field(min_length=1)
