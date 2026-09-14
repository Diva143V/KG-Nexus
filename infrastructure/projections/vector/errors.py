"""Vector projection backend errors.

Every failure in this backend is a ``VectorProjectionError`` subtype so
callers can catch the whole family with one type.
"""

from __future__ import annotations


class VectorProjectionError(Exception):
    """Base error for the vector projection backend."""


class VectorClientError(VectorProjectionError):
    """Raised when the underlying vector store rejects an operation."""


class MissingVectorReleaseError(VectorProjectionError):
    """Raised when no RDF release exists for the requested release id."""

    def __init__(self, release_id: str) -> None:
        super().__init__(f"no RDF release available for release: {release_id}")
        self.release_id = release_id


class UnknownVectorProjectionError(VectorProjectionError):
    """Raised when a projection id was never built in this backend."""

    def __init__(self, projection_id: str) -> None:
        super().__init__(f"unknown vector projection: {projection_id}")
        self.projection_id = projection_id


class VectorUnsupportedSemanticsError(VectorProjectionError):
    """Raised when the profile declares a predicate unsupported with ERROR."""

    def __init__(self, predicate: str, profile_id: str) -> None:
        super().__init__(f"profile {profile_id} declares unsupported predicate: {predicate}")
        self.predicate = predicate
        self.profile_id = profile_id


class VectorValidationError(VectorProjectionError):
    """Raised when a candidate fails validation."""


class VectorReconciliationError(VectorProjectionError):
    """Raised when a candidate does not match its RDF release."""


class VectorSmokeTestError(VectorProjectionError):
    """Raised when a candidate fails its smoke tests."""


class VectorIndexError(VectorProjectionError):
    """Raised when vector indexing or retrieval fails."""
