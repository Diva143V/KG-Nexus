"""Release lifecycle: the release model and its gate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier
from core.releases.manifest import ReleaseManifest
from core.releases.status import ReleaseStatus


class ReleaseTransition(BaseModel):
    """A single recorded transition in a release's lifecycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_status: ReleaseStatus
    to_status: ReleaseStatus
    at: datetime
    reason: str = ""


class ReleaseGate(BaseModel):
    """The checks a release must pass before it can be APPROVED.

    Each required validation category is recorded independently so the
    gate is auditable. ``passed`` is true only when every required check
    has passed. This is distinct from any release severity; it is a
    boolean gate over validation results.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    structural: bool = False
    logical: bool = False
    application: bool = False
    evidence: bool = False
    projection: bool = False
    reconciliation: bool = False

    @property
    def passed(self) -> bool:
        """True when every required check has passed."""
        return (
            self.structural
            and self.logical
            and self.application
            and self.evidence
            and self.projection
            and self.reconciliation
        )


class Release(BaseModel):
    """An immutable release of the knowledge graph.

    A release references its manifest and is driven through a lifecycle
    by ``ReleaseManager``. The object itself never mutates: every
    transition produces a new instance with an appended audit trail.
    Once ``PUBLISHED``, no further transitions are allowed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    version: str = Field(min_length=1)
    status: ReleaseStatus
    manifest: ReleaseManifest
    created_at: datetime
    published_at: datetime | None = None
    gate: ReleaseGate | None = None
    quarantine_reasons: tuple[str, ...] = Field(default_factory=tuple)
    transitions: tuple[ReleaseTransition, ...] = Field(default_factory=tuple)

    @property
    def is_published(self) -> bool:
        return self.status is ReleaseStatus.PUBLISHED

    @property
    def is_quarantined(self) -> bool:
        return self.status is ReleaseStatus.QUARANTINED


def now_utc() -> datetime:
    """Current UTC timestamp for lifecycle events."""
    return datetime.now(UTC)


def record_transition(
    release: Release,
    to_status: ReleaseStatus,
    *,
    at: datetime,
    reason: str,
    gate: ReleaseGate | None = None,
    quarantine_reasons: tuple[str, ...] = (),
) -> Release:
    """Return a new Release advanced to ``to_status`` with a transition record."""
    transition = ReleaseTransition(
        from_status=release.status,
        to_status=to_status,
        at=at,
        reason=reason,
    )
    fields: dict[str, Any] = {
        "id": release.id,
        "version": release.version,
        "status": to_status,
        "manifest": release.manifest,
        "created_at": release.created_at,
        "published_at": release.published_at,
        "gate": gate if gate is not None else release.gate,
        "quarantine_reasons": quarantine_reasons or release.quarantine_reasons,
        "transitions": release.transitions + (transition,),
    }
    if to_status is ReleaseStatus.PUBLISHED:
        fields["published_at"] = at
    return Release(**fields)
