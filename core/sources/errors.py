"""Source lifecycle errors."""

from __future__ import annotations

from core.identifiers.identifier import Identifier


class SourceError(Exception):
    """Base class for source lifecycle errors."""


class UnknownSourceError(SourceError):
    """Raised when a release is requested for an unregistered source."""

    def __init__(self, source_id: Identifier) -> None:
        self.source_id = source_id
        super().__init__(f"unknown source: {source_id.canonical}")


class UnknownReleaseError(SourceError):
    """Raised when ingesting a release not created by the manager."""

    def __init__(self, release_id: Identifier) -> None:
        self.release_id = release_id
        super().__init__(f"unknown release: {release_id.canonical}")
