"""Projection lifecycle management.

Drives a ``Projection`` through its lifecycle, enforcing the rules:

* a projection cannot become READY until validation and reconciliation pass;
* a projection cannot become ACTIVE unless READY;
* active projections cannot be changed in place;
* retained projections exist only for rollback and are terminal.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from core.identifiers.identifier import Identifier
from core.validation.result import ValidationStatus
from infrastructure.projections.legacy_framework.content import ProjectionContent
from infrastructure.projections.legacy_framework.errors import (
    ActiveProjectionError,
    InvalidProjectionTransitionError,
    ProjectionValidationError,
    UnknownProjectionError,
)
from infrastructure.projections.legacy_framework.profile import ProjectionProfile
from infrastructure.projections.legacy_framework.projection import (
    Projection,
    ProjectionGate,
    now_utc,
    record_transition,
)
from infrastructure.projections.legacy_framework.resolver import ProjectionStatusResolver
from infrastructure.projections.legacy_framework.status import ProjectionStatus
from infrastructure.projections.legacy_framework.validator import ProjectionValidator


class ProjectionManager:
    """Owns projections and enforces the projection lifecycle."""

    def __init__(
        self,
        *,
        resolver: ProjectionStatusResolver | None = None,
        validator: ProjectionValidator | None = None,
    ) -> None:
        self._resolver = resolver or ProjectionStatusResolver()
        self._validator = validator or ProjectionValidator()
        self._projections: dict[str, Projection] = {}

    def create_projection(
        self,
        *,
        projection_id: Identifier,
        name: str,
        profile: ProjectionProfile,
        created_at: datetime | None = None,
    ) -> Projection:
        """Create a new projection in BUILDING state."""
        key = projection_id.canonical
        if key in self._projections:
            raise ValueError(f"duplicate projection: {key}")
        projection = Projection(
            id=projection_id,
            name=name,
            profile=profile,
            status=ProjectionStatus.BUILDING,
            created_at=created_at or now_utc(),
        )
        self._projections[key] = projection
        return projection

    def get_projection(self, projection_id: Identifier) -> Projection | None:
        """Return the latest recorded instance of a projection, if any."""
        return self._projections.get(projection_id.canonical)

    def iter_projections(self) -> Iterable[Projection]:
        """Iterate over all projections currently recorded."""
        return self._projections.values()

    def begin_validation(
        self,
        projection: Projection,
        *,
        content: ProjectionContent,
        at: datetime | None = None,
    ) -> Projection:
        """Attach content and move BUILDING -> VALIDATING."""
        return self._transition(
            projection,
            ProjectionStatus.VALIDATING,
            at=at,
            reason="projection built",
            content=content,
        )

    def complete_validation(
        self,
        projection: Projection,
        *,
        gate: ProjectionGate,
        activity_id: Identifier,
        at: datetime | None = None,
    ) -> Projection:
        """Validate and reconcile: VALIDATING -> RECONCILED.

        The projection must pass both validation (audit trails against the
        profile) and reconciliation (matching the authoritative RDF). If the
        gate fails, the projection is not advanced.
        """
        self._require_current(projection)
        if projection.content is None:
            raise ValueError("projection has no content")
        results = self._validator.validate(
            content=projection.content,
            profile=projection.profile,
            activity_id=activity_id,
        )
        validation_passed = all(result.status is not ValidationStatus.FAIL for result in results)
        if not gate.passed or not validation_passed:
            reasons = []
            if not validation_passed:
                reasons.append("projection validation failed")
            if not gate.reconciliation:
                reasons.append("reconciliation failed")
            if not gate.validation:
                reasons.append("validation gate failed")
            raise ProjectionValidationError(projection.id, reasons)
        return self._transition(
            projection,
            ProjectionStatus.RECONCILED,
            at=at,
            reason="validation and reconciliation passed",
            gate=gate,
        )

    def mark_ready(
        self,
        projection: Projection,
        *,
        at: datetime | None = None,
    ) -> Projection:
        """Move RECONCILED -> READY."""
        return self._transition(
            projection, ProjectionStatus.READY, at=at, reason="projection ready"
        )

    def activate(
        self,
        projection: Projection,
        *,
        at: datetime | None = None,
    ) -> Projection:
        """Activate a READY projection: READY -> ACTIVE.

        The projection content is not re-written here; activation records
        that the projection is in service. Backend writes are the concern of
        the projection backend adapter, not Core.
        """
        return self._transition(
            projection, ProjectionStatus.ACTIVE, at=at, reason="projection activated"
        )

    def retain_for_rollback(
        self,
        projection: Projection,
        *,
        at: datetime | None = None,
    ) -> Projection:
        """Retain an ACTIVE projection for rollback: ACTIVE -> RETAINED_FOR_ROLLBACK.

        After this transition the projection is terminal and cannot change.
        """
        return self._transition(
            projection,
            ProjectionStatus.RETAINED_FOR_ROLLBACK,
            at=at,
            reason="retained for rollback",
        )

    def _transition(
        self,
        projection: Projection,
        target: ProjectionStatus,
        *,
        at: datetime | None,
        reason: str,
        gate: ProjectionGate | None = None,
        content: ProjectionContent | None = None,
    ) -> Projection:
        self._require_current(projection)
        if projection.is_retained:
            raise ActiveProjectionError(projection.id)
        if projection.is_active and target is not ProjectionStatus.RETAINED_FOR_ROLLBACK:
            raise ActiveProjectionError(projection.id)
        if not self._resolver.can_transition(projection.status, target):
            raise InvalidProjectionTransitionError(projection.status, target)
        updated = record_transition(
            projection,
            target,
            at=at or now_utc(),
            reason=reason,
            gate=gate,
        )
        if content is not None:
            updated = updated.model_copy(update={"content": content})
        self._projections[projection.id.canonical] = updated
        return updated

    def _require_current(self, projection: Projection) -> None:
        current = self._projections.get(projection.id.canonical)
        if current is None:
            raise UnknownProjectionError(projection.id)
        if current is not projection:
            raise UnknownProjectionError(projection.id)
