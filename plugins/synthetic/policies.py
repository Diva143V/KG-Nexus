"""Synthetic Domain Identity and Evidence Policies."""

from __future__ import annotations

from pydantic import BaseModel

from core.entities.entity import Entity
from core.resolution.models import CandidateMatch, IdentityDecision


class SyntheticIdentityPolicy:
    """Identity policy for Synthetic Domain entities."""

    @property
    def method(self) -> str:
        return "synthetic_identity_policy_v1"

    def decide(
        self,
        *,
        source: Entity,
        candidate: CandidateMatch,
    ) -> IdentityDecision:
        # Exact identifier match or score >= 0.9
        same_id = (
            source.id.namespace == candidate.candidate_entity.id.namespace
            and source.id.value == candidate.candidate_entity.id.value
        )
        accepted = same_id or candidate.ranking_score >= 0.9
        return IdentityDecision(
            source_entity=source,
            candidate_entity=candidate.candidate_entity,
            accepted=accepted,
            method=self.method,
            activity_id=candidate.activity_id,
        )


class SyntheticEvidencePolicy(BaseModel):
    """Simple evidence policy for synthetic domain assertions."""

    policy_id: str = "synthetic_evidence_policy_v1"
    min_confidence: float = 0.5
    require_provenance: bool = True

    def evaluate(self, confidence: float, has_provenance: bool) -> bool:
        if self.require_provenance and not has_provenance:
            return False
        return confidence >= self.min_confidence
