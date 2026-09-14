"""Release lifecycle errors."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.releases.status import ReleaseStatus


class ReleaseError(Exception):
    """Base class for release lifecycle errors."""


class UnknownReleaseError(ReleaseError):
    """Raised when operating on a release not managed by the manager."""

    def __init__(self, release_id: Identifier) -> None:
        self.release_id = release_id
        super().__init__(f"unknown release: {release_id.canonical}")


class InvalidReleaseTransitionError(ReleaseError):
    """Raised when a release attempts an illegal status transition."""

    def __init__(self, current: ReleaseStatus, target: ReleaseStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid release transition: {current.value} -> {target.value}")


class PublishedReleaseError(ReleaseError):
    """Raised when mutating a published (immutable) release."""

    def __init__(self, release_id: Identifier) -> None:
        self.release_id = release_id
        super().__init__(f"published releases are immutable: {release_id.canonical}")
