"""Evidence: links between assertions and supporting records."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class EvidenceKind(StrEnum):
    """How directly a record supports a claim."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNSPECIFIED = "unspecified"


class Evidence(BaseModel):
    """A reference from a claim to a supporting parsed record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    kind: EvidenceKind = EvidenceKind.UNSPECIFIED
    record_id: Identifier
    artifact_id: Identifier | None = None
    obtained_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
