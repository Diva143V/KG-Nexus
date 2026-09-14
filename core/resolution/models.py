"""Resolution result models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.entities.entity import Entity
from core.identifiers.identifier import Identifier


class CandidateMatch(BaseModel):
    """A ranked candidate for a source entity, with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_entity: Entity
    candidate_entity: Entity
    ranking_score: float = Field(ge=0.0, le=1.0)
    ranking_method: str = Field(min_length=1)
    activity_id: Identifier


class IdentityDecision(BaseModel):
    """Outcome of an identity policy for a single candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_entity: Entity
    candidate_entity: Entity
    accepted: bool
    method: str = Field(min_length=1)
    activity_id: Identifier
