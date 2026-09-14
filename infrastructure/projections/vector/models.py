"""Data models for the vector projection.

``EmbeddedItem`` is one vector plus its retrieval metadata. It carries exactly
the backend-neutral record facts Core needs (``kind``, ``key``, ``digest``)
plus the embedding surface and the source assertion it was derived from. It
deliberately carries no state and no truth claim: a vector is a retrieval
candidate, never an identity or an approval.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EmbeddedItem(BaseModel):
    """One embedded retrieval target (entity, relation, or assertion)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    text: str = Field(min_length=0)
    vector: tuple[float, ...] = Field(min_length=1)
    source: str | None = None
