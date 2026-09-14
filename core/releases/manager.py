"""Release lifecycle management.

Drives a ``Release`` through its lifecycle, enforcing the rules:

* a release cannot become APPROVED until the release gate passes
  (structural, logical, application, evidence, projection validation
  and reconciliation);
* a release cannot become PUBLISHED unless APPROVED;
* failed releases move to QUARANTINED;
* releases are immutable once PUBLISHED.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from core.identifiers.identifier import Identifier
from core.releases.errors import (
    InvalidReleaseTransitionError,
    PublishedReleaseError,
    UnknownReleaseError,
)
from core.releases.manifest import ReleaseManifest
from core.releases.release import Release, ReleaseGate, now_utc, record_transition
from core.releases.resolver import ReleaseStatusResolver
from core.releases.status import ReleaseStatus


class ReleaseManager:
    """Owns releases and enforces the release lifecycle."""

    def __init__(
        self,
        *,
        resolver: ReleaseStatusResolver | None = None,
    ) -> None:
        self._resolver = resolver or ReleaseStatusResolver()
        self._releases: dict[str, Release] = {}

    def create_release(
        self,
        *,
        release_id: Identifier,
        version: str,
        manifest: ReleaseManifest,
        created_at: datetime | None = None,
    ) -> Release:
        """Create a new release in CANDIDATE state."""
        key = release_id.canonical
        if key in self._releases:
            raise ValueError(f"duplicate release: {key}")
        release = Release(
            id=release_id,
            version=version,
            status=ReleaseStatus.CANDIDATE,
            manifest=manifest,
            created_at=created_at or now_utc(),
        )
        self._releases[key] = release
        return release

    def get_release(self, release_id: Identifier) -> Release | None:
        """Return the latest recorded instance of a release, if any."""
        return self._releases.get(release_id.canonical)

    def iter_releases(self) -> Iterable[Release]:
        """Iterate over all releases currently recorded."""
        return self._releases.values()

    def update_manifest(self, release: Release, manifest: ReleaseManifest) -> Release:
        """Update the manifest of an un-published release."""
        self._require_current(release)
        if release.is_published:
            raise PublishedReleaseError(release.id)
        updated = Release(
            id=release.id,
            version=release.version,
            status=release.status,
            manifest=manifest,
            created_at=release.created_at,
            published_at=release.published_at,
            gate=release.gate,
            quarantine_reasons=release.quarantine_reasons,
            transitions=release.transitions,
        )
        self._releases[release.id.canonical] = updated
        return updated

    def begin_validation(self, release: Release, *, at: datetime | None = None) -> Release:
        """Move CANDIDATE -> VALIDATING."""
        return self._transition(
            release, ReleaseStatus.VALIDATING, at=at, reason="validation started"
        )

    def complete_validation(
        self,
        release: Release,
        *,
        gate: ReleaseGate,
        at: datetime | None = None,
    ) -> Release:
        """Complete validation: VALIDATING -> VALIDATED, or QUARANTINED.

        Validation passes when structural, logical, application,
        evidence, and projection checks all pass.
        """
        self._require_current(release)
        validation_passed = gate.structural and gate.logical and gate.application and gate.evidence
        if validation_passed:
            return self._transition(
                release,
                ReleaseStatus.VALIDATED,
                at=at,
                reason="validation passed",
                gate=gate,
            )
        return self.quarantine(release, at=at, reasons=("validation failed",))

    def project(self, release: Release, *, at: datetime | None = None) -> Release:
        """Move VALIDATED -> PROJECTED."""
        return self._transition(
            release, ReleaseStatus.PROJECTED, at=at, reason="projection complete"
        )

    def reconcile(
        self,
        release: Release,
        *,
        gate: ReleaseGate,
        at: datetime | None = None,
    ) -> Release:
        """Reconcile: PROJECTED -> RECONCILED, or QUARANTINED.

        Reconciliation passes when the gate's reconciliation check and
        the projection validation pass.
        """
        self._require_current(release)
        if gate.reconciliation and gate.projection:
            return self._transition(
                release,
                ReleaseStatus.RECONCILED,
                at=at,
                reason="reconciliation complete",
                gate=gate,
            )
        return self.quarantine(release, at=at, reasons=("reconciliation failed",))

    def approve(
        self,
        release: Release,
        *,
        gate: ReleaseGate,
        at: datetime | None = None,
    ) -> Release:
        """Approve a release: RECONCILED -> APPROVED, or QUARANTINED.

        A release cannot become APPROVED until every required check in
        the release gate has passed.
        """
        self._require_current(release)
        if gate.passed:
            return self._transition(
                release,
                ReleaseStatus.APPROVED,
                at=at,
                reason="release gate passed",
                gate=gate,
            )
        return self.quarantine(release, at=at, reasons=("release gate failed",))

    def publish(self, release: Release, *, at: datetime | None = None) -> Release:
        """Publish an APPROVED release: APPROVED -> PUBLISHED.

        A release cannot become PUBLISHED unless APPROVED. After this
        transition the release is immutable.
        """
        return self._transition(release, ReleaseStatus.PUBLISHED, at=at, reason="published")

    def quarantine(
        self,
        release: Release,
        *,
        at: datetime | None = None,
        reasons: Iterable[str] = (),
    ) -> Release:
        """Move a failed release to QUARANTINED (from any non-terminal state)."""
        return self._transition(
            release,
            ReleaseStatus.QUARANTINED,
            at=at,
            reason="quarantined",
            quarantine_reasons=tuple(reasons),
        )

    def _transition(
        self,
        release: Release,
        target: ReleaseStatus,
        *,
        at: datetime | None,
        reason: str,
        gate: ReleaseGate | None = None,
        quarantine_reasons: tuple[str, ...] = (),
    ) -> Release:
        self._require_current(release)
        if release.is_published:
            raise PublishedReleaseError(release.id)
        if not self._resolver.can_transition(release.status, target):
            raise InvalidReleaseTransitionError(release.status, target)
        updated = record_transition(
            release,
            target,
            at=at or now_utc(),
            reason=reason,
            gate=gate,
            quarantine_reasons=quarantine_reasons,
        )
        self._releases[release.id.canonical] = updated
        return updated

    def _require_current(self, release: Release) -> None:
        current = self._releases.get(release.id.canonical)
        if current is None:
            raise UnknownReleaseError(release.id)
        if current is not release:
            raise UnknownReleaseError(release.id)
