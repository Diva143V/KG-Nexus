"""Resolution extension contracts.

Resolution mechanics (blocking, retrieval, ranking) live in core.
Domain-specific identity semantics enter exclusively through the
``IdentityPolicy`` contract; candidate generation never decides
semantic identity by itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.entities.entity import Entity
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch, IdentityDecision


@runtime_checkable
class CandidateRetriever(Protocol):
    """Retrieves candidate entities for a source entity."""

    def retrieve(self, *, source: Entity, activity_id: Identifier) -> list[Entity]:
        """Return candidate entities for ``source``."""
        ...


@runtime_checkable
class CandidateRanker(Protocol):
    """Assigns a deterministic ranking score to a candidate."""

    @property
    def method(self) -> str:
        """Stable identifier for the ranking method."""
        ...

    def score(self, source: Entity, candidate: Entity) -> float:
        """Return a score in ``[0.0, 1.0]``; higher means more similar."""
        ...


@runtime_checkable
class CandidateGenerator(Protocol):
    """Generates ranked candidate matches for a source entity."""

    def generate(
        self,
        *,
        source: Entity,
        activity_id: Identifier,
    ) -> list[CandidateMatch]:
        """Return ranked candidate matches for ``source``."""
        ...


@runtime_checkable
class IdentityPolicy(Protocol):
    """Decides identity for a candidate. Domain meaning lives here."""

    @property
    def method(self) -> str:
        """Stable identifier for the identity policy."""
        ...

    def decide(
        self,
        *,
        source: Entity,
        candidate: CandidateMatch,
    ) -> IdentityDecision:
        """Decide whether ``candidate`` is the same entity as ``source``."""
        ...
