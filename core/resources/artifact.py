"""Artifacts: immutable, content-addressed data products of a release."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.identifiers.identifier import Identifier

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ArtifactKind(StrEnum):
    """Domain-neutral categories of artifacts."""

    DOCUMENT = "document"
    DATASET = "dataset"
    PAYLOAD = "payload"
    OTHER = "other"


class Artifact(BaseModel):
    """A concrete artifact obtained from a release.

    Artifacts are immutable. Identical content always maps to the same
    artifact; content is never overwritten.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    source_release_id: Identifier
    kind: ArtifactKind = ArtifactKind.OTHER
    name: str | None = Field(default=None, min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str
    size_bytes: int = Field(ge=0)
    retrieved_at: datetime

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("must be a lowercase 64-character hex sha256 digest")
        return value
