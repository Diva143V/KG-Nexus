"""Identity policies.

Core must never decide semantic identity. The only policy provided here
is a null policy that never accepts a candidate.
"""

from __future__ import annotations

from core.entities.entity import Entity
from core.resolution.models import CandidateMatch, IdentityDecision


class NullIdentityPolicy:
    """Never accepts a candidate; identity is left undecided."""

    method = "null"

    def decide(
        self,
        *,
        source: Entity,
        candidate: CandidateMatch,
    ) -> IdentityDecision:
        return IdentityDecision(
            source_entity=source,
            candidate_entity=candidate.candidate_entity,
            accepted=False,
            method=self.method,
            activity_id=candidate.activity_id,
        )
