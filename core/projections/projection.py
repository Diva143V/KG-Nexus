"""The projection model and its lifecycle gate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier
from core.projections.content import ProjectionContent
from core.projections.profile import ProjectionProfile
from core.projections.status import ProjectionStatus


class ProjectionTransition(BaseModel):
    """A single recorded transition in a projection's lifecycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_status: ProjectionStatus
    to_status: ProjectionStatus
    at: datetime
    reason: str = ""


class ProjectionGate(BaseModel):
    """The checks a projection must pass before it becomes READY.

    ``validation`` covers projection validation (audit trails against the
    profile); ``reconciliation`` covers matching the authoritative RDF.
    ``passed`` is true only when both checks pass.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    validation: bool = False
    reconciliation: bool = False

    @property
    def passed(self) -> bool:
        """True when every required check has passed."""
        return self.validation and self.reconciliation


class Projection(BaseModel):
    """An immutable projection definition and its lifecycle.

    A projection is always a view over the authoritative RDF: it is rebuilt
    from the RDF source and reconciled against it. The object itself never
    mutates; every transition produces a new instance with an appended
    audit trail. ACTIVE projections cannot be changed in place; retained
    projections exist only for rollback.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    name: str = Field(min_length=1)
    profile: ProjectionProfile
    status: ProjectionStatus = ProjectionStatus.BUILDING
    content: ProjectionContent | None = None
    created_at: datetime
    activated_at: datetime | None = None
    gate: ProjectionGate | None = None
    transitions: tuple[ProjectionTransition, ...] = Field(default_factory=tuple)

    @property
    def is_active(self) -> bool:
        return self.status is ProjectionStatus.ACTIVE

    @property
    def is_retained(self) -> bool:
        return self.status is ProjectionStatus.RETAINED_FOR_ROLLBACK


def now_utc() -> datetime:
    """Current UTC timestamp for lifecycle events."""
    return datetime.now(UTC)


def record_transition(
    projection: Projection,
    to_status: ProjectionStatus,
    *,
    at: datetime,
    reason: str,
    gate: ProjectionGate | None = None,
) -> Projection:
    """Return a new Projection advanced to ``to_status`` with a transition record."""
    transition = ProjectionTransition(
        from_status=projection.status,
        to_status=to_status,
        at=at,
        reason=reason,
    )
    fields: dict[str, Any] = {
        "id": projection.id,
        "name": projection.name,
        "profile": projection.profile,
        "status": to_status,
        "content": projection.content,
        "created_at": projection.created_at,
        "activated_at": projection.activated_at,
        "gate": gate if gate is not None else projection.gate,
        "transitions": projection.transitions + (transition,),
    }
    if to_status is ProjectionStatus.ACTIVE:
        fields["activated_at"] = at
    return Projection(**fields)
