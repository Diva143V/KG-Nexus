"""Digest profiles: which fields participate in the identity digest."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DigestProfile(BaseModel):
    """Configuration of what a canonical digest covers.

    By default provenance does not participate in the identity digest:
    provenance-only changes never alter the digest unless
    ``include_provenance`` is enabled explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(default="1", min_length=1)
    include_provenance: bool = False
