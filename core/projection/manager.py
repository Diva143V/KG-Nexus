"""Pluggable projection lifecycle management.

Owns projections and drives them through the backend-independent lifecycle
while delegating all actual storage to a pluggable ``ProjectionBackend``:

* candidates move BUILDING -> VALIDATING -> RECONCILING -> READY;
* a READY candidate is activated atomically — the current ACTIVE projection
  is retained for rollback and the candidate becomes ACTIVE;
* an ACTIVE projection can be rolled back to the previously retained one;
* failed and quarantined projections are never activated.

Core is the authority on the lifecycle; backends only store projections.
Nothing here knows what a backend is.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier
from core.projection.backend import ProjectionBackend
from core.projection.errors import (
    ActiveProjectionError,
    InvalidProjectionTransitionError,
    NoActiveProjectionError,
    NoRetainedProjectionError,
    UnknownProjectionError,
)
from core.projection.lifecycle import (
    ProjectionStatus,
    ProjectionStatusResolver,
    ProjectionTransition,
    now_utc,
    record_transition,
)
from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import (
    ProjectionReconciler,
    ReconciliationResult,
)
from core.projection.registry import ProjectionRegistry
from core.projection.result import ProjectionResult, ProjectionValidationResult
from core.rdf.graph import RDFDataset


class Projection(BaseModel):
    """One projection instance, in backend-neutral terms."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    profile: ProjectionProfile
    backend_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    status: ProjectionStatus = ProjectionStatus.BUILDING
    created_at: datetime
    activated_at: datetime | None = None
    retained_at: datetime | None = None
    build_result: ProjectionResult | None = None
    validation_result: ProjectionValidationResult | None = None
    reconciliation_result: ReconciliationResult | None = None
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    transitions: tuple[ProjectionTransition, ...] = Field(default_factory=tuple)

    @property
    def is_active(self) -> bool:
        """Whether the projection is currently in service."""
        return self.status is ProjectionStatus.ACTIVE

    @property
    def is_retained(self) -> bool:
        """Whether the projection is retained for rollback."""
        return self.status is ProjectionStatus.RETAINED_FOR_ROLLBACK

    @property
    def is_candidate(self) -> bool:
        """Whether the projection is still working toward READY."""
        return self.status in (
            ProjectionStatus.BUILDING,
            ProjectionStatus.VALIDATING,
            ProjectionStatus.RECONCILING,
            ProjectionStatus.READY,
        )

    @property
    def is_failed(self) -> bool:
        """Whether the projection has failed or been quarantined."""
        return self.status in (ProjectionStatus.FAILED, ProjectionStatus.QUARANTINED)


class ProjectionManager:
    """Owns projections and enforces the pluggable projection lifecycle."""

    def __init__(
        self,
        *,
        registry: ProjectionRegistry,
        resolver: ProjectionStatusResolver | None = None,
        reconciler: ProjectionReconciler | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or ProjectionStatusResolver()
        self._reconciler = reconciler or ProjectionReconciler()
        self._clock = clock or now_utc
        self._projections: dict[str, Projection] = {}
        self._backends: dict[str, ProjectionBackend] = {}

    def _backend(self, backend_id: str) -> ProjectionBackend:
        if backend_id not in self._backends:
            self._backends[backend_id] = self._registry.get(backend_id)
        return self._backends[backend_id]

    def create_projection(
        self,
        *,
        projection_id: Identifier,
        profile: ProjectionProfile,
        backend_id: str,
        release_id: str,
        created_at: datetime | None = None,
    ) -> Projection:
        """Create a new projection in BUILDING state."""
        key = projection_id.canonical
        if key in self._projections:
            raise ValueError(f"duplicate projection: {key}")
        self._backend(backend_id)
        projection = Projection(
            id=projection_id,
            profile=profile,
            backend_id=backend_id,
            release_id=release_id,
            status=ProjectionStatus.BUILDING,
            created_at=created_at or self._clock(),
        )
        self._projections[key] = projection
        return projection

    def get_projection(self, projection_id: Identifier) -> Projection | None:
        """Return the recorded instance of a projection, if any."""
        return self._projections.get(projection_id.canonical)

    def iter_projections(self) -> Iterable[Projection]:
        """Iterate over all projections currently recorded."""
        return self._projections.values()

    def active_projection(self) -> Projection | None:
        """Return the current ACTIVE projection, if any.

        The manager enforces at most one ACTIVE projection at a time.
        """
        for projection in self._projections.values():
            if projection.is_active:
                return projection
        return None

    def candidate_projection(self) -> Projection | None:
        """Return the latest projection still working toward READY, if any."""
        candidate: Projection | None = None
        for projection in self._projections.values():
            if projection.is_candidate:
                if candidate is None or projection.created_at > candidate.created_at:
                    candidate = projection
        return candidate

    def build_candidate(self, projection_id: Identifier) -> Projection:
        """Build a candidate: BUILDING -> VALIDATING, or FAILED."""
        projection = self._require(projection_id)
        backend = self._backend(projection.backend_id)
        try:
            result = backend.build(
                projection_id=projection.id.canonical,
                release_id=projection.release_id,
                profile=projection.profile,
            )
        except Exception as exc:  # backend failure always fails the candidate
            return self._fail(projection, f"build failed: {exc}")
        return self._transition(
            projection,
            ProjectionStatus.VALIDATING,
            reason="build completed",
            update={"build_result": result},
        )

    def validate_candidate(self, projection_id: Identifier) -> Projection:
        """Validate a candidate: VALIDATING -> RECONCILING, or FAILED."""
        projection = self._require(projection_id)
        backend = self._backend(projection.backend_id)
        try:
            result = backend.validate(projection.id.canonical)
        except Exception as exc:
            return self._fail(projection, f"validation failed: {exc}")
        if not result.passed:
            detail = "; ".join(result.errors) if result.errors else "validation failed"
            return self._fail(
                projection,
                detail,
                update={"validation_result": result},
            )
        return self._transition(
            projection,
            ProjectionStatus.RECONCILING,
            reason="validation passed",
            update={"validation_result": result},
        )

    def reconcile_candidate(
        self,
        projection_id: Identifier,
        dataset: RDFDataset,
    ) -> Projection:
        """Reconcile a candidate against the RDF: RECONCILING -> READY, or FAILED."""
        projection = self._require(projection_id)
        backend = self._backend(projection.backend_id)
        records = backend.records(projection.id.canonical)
        result = self._reconciler.reconcile(
            projection_id=projection.id.canonical,
            release_id=projection.release_id,
            profile=projection.profile,
            dataset=dataset,
            projected_records=records,
        )
        if not result.reconciled:
            return self._fail(
                projection,
                f"reconciliation failed: {self._reconciliation_detail(result)}",
                update={"reconciliation_result": result},
            )
        return self._transition(
            projection,
            ProjectionStatus.READY,
            reason="reconciliation passed",
            update={"reconciliation_result": result},
        )

    def activate_candidate(self, projection_id: Identifier) -> Projection:
        """Activate a READY candidate atomically: READY -> ACTIVE.

        The current ACTIVE projection, if any, is retained for rollback
        first; the candidate then becomes ACTIVE. Backend activation is
        delegated to the backend, which is responsible for atomic switching
        on its own side.
        """
        candidate = self._require(projection_id)
        if candidate.status is not ProjectionStatus.READY:
            raise InvalidProjectionTransitionError(candidate.status, ProjectionStatus.ACTIVE)
        backend = self._backend(candidate.backend_id)
        try:
            backend.activate(candidate.id.canonical)
        except Exception as exc:
            return self._fail(candidate, f"activation failed: {exc}")
        current = self.active_projection()
        if current is not None:
            current = self._transition(
                current,
                ProjectionStatus.RETAINED_FOR_ROLLBACK,
                reason="retained for rollback",
            )
        return self._transition(
            candidate,
            ProjectionStatus.ACTIVE,
            reason="activated",
        )

    def rollback(self, projection_id: Identifier) -> Projection:
        """Roll back the ACTIVE projection to the previously retained one."""
        active = self._require(projection_id)
        if active.status is not ProjectionStatus.ACTIVE:
            raise NoActiveProjectionError(active.id.canonical)
        retained = self._retained_projection()
        if retained is None:
            raise NoRetainedProjectionError(active.id.canonical)
        backend = self._backend(active.backend_id)
        try:
            backend.rollback(active.id.canonical)
        except Exception as exc:
            return self._fail(active, f"rollback failed: {exc}")
        self._transition(
            active,
            ProjectionStatus.RETAINED_FOR_ROLLBACK,
            reason="rolled back",
        )
        return self._transition(
            retained,
            ProjectionStatus.ACTIVE,
            reason="restored by rollback",
        )

    def fail(self, projection_id: Identifier, *, reason: str) -> Projection:
        """Fail a projection explicitly (from any state that allows FAILED)."""
        projection = self._require(projection_id)
        return self._fail(projection, reason)

    def quarantine(
        self,
        projection_id: Identifier,
        *,
        reason: str,
    ) -> Projection:
        """Quarantine a projection (terminal)."""
        projection = self._require(projection_id)
        return self._transition(
            projection,
            ProjectionStatus.QUARANTINED,
            reason=reason,
        )

    def destroy(self, projection_id: Identifier) -> None:
        """Destroy a projection; ACTIVE projections must be handled first."""
        projection = self._require(projection_id)
        if projection.is_active:
            raise ActiveProjectionError(projection.id.canonical)
        backend = self._backend(projection.backend_id)
        backend.destroy(projection.id.canonical)
        del self._projections[projection.id.canonical]

    def _fail(
        self,
        projection: Projection,
        reason: str,
        *,
        update: dict[str, object] | None = None,
    ) -> Projection:
        return self._transition(
            projection,
            ProjectionStatus.FAILED,
            reason=reason,
            update=update,
        )

    def _transition(
        self,
        projection: Projection,
        target: ProjectionStatus,
        *,
        reason: str,
        update: dict[str, object] | None = None,
    ) -> Projection:
        self._require_current(projection)
        if not self._resolver.can_transition(projection.status, target):
            raise InvalidProjectionTransitionError(projection.status, target)
        at = self._clock()
        fields: dict[str, object] = {
            "transitions": record_transition(
                from_status=projection.status,
                to_status=target,
                at=at,
                reason=reason,
                transitions=projection.transitions,
            ),
            "status": target,
        }
        if target is ProjectionStatus.ACTIVE:
            fields["activated_at"] = at
        if target is ProjectionStatus.RETAINED_FOR_ROLLBACK:
            fields["retained_at"] = at
        if target in (ProjectionStatus.FAILED, ProjectionStatus.QUARANTINED):
            fields["reasons"] = projection.reasons + (reason,)
        if update is not None:
            fields.update(update)
        updated = projection.model_copy(update=fields)
        self._projections[projection.id.canonical] = updated
        return updated

    def _retained_projection(self) -> Projection | None:
        retained = [p for p in self._projections.values() if p.is_retained]
        if not retained:
            return None
        return max(retained, key=lambda p: p.retained_at or p.created_at)

    def _require(self, projection_id: Identifier) -> Projection:
        projection = self._projections.get(projection_id.canonical)
        if projection is None:
            raise UnknownProjectionError(projection_id.canonical)
        return projection

    def _require_current(self, projection: Projection) -> None:
        current = self._projections.get(projection.id.canonical)
        if current is not projection:
            raise UnknownProjectionError(projection.id.canonical)

    @staticmethod
    def _reconciliation_detail(result: ReconciliationResult) -> str:
        report = result.report
        parts = [
            f"missing={len(report.missing_records)}",
            f"unexpected={len(report.unexpected_records)}",
            f"transformed={len(report.transformed_records)}",
        ]
        return ", ".join(parts)
