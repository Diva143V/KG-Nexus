"""RDF projection backend errors.

Every failure in this backend is an ``RDFProjectionError`` subtype so
callers can catch the whole family with one type.
"""

from __future__ import annotations


class RDFProjectionError(Exception):
    """Base error for the RDF projection backend."""


class RDFClientError(RDFProjectionError):
    """Raised when the underlying RDF store rejects an operation."""


class MissingRDFReleaseError(RDFProjectionError):
    """Raised when no RDF release exists for the requested release id."""

    def __init__(self, release_id: str) -> None:
        super().__init__(f"no RDF release available for release: {release_id}")
        self.release_id = release_id


class UnknownRDFProjectionError(RDFProjectionError):
    """Raised when a projection id was never built in this backend."""

    def __init__(self, projection_id: str) -> None:
        super().__init__(f"unknown RDF projection: {projection_id}")
        self.projection_id = projection_id


class RDFUnsupportedSemanticsError(RDFProjectionError):
    """Raised when the profile declares a predicate unsupported with ERROR."""

    def __init__(self, predicate: str, profile_id: str) -> None:
        super().__init__(f"profile {profile_id} declares unsupported predicate: {predicate}")
        self.predicate = predicate
        self.profile_id = profile_id


class RDFValidationError(RDFProjectionError):
    """Raised when a candidate fails validation."""


class RDFReconciliationError(RDFProjectionError):
    """Raised when a candidate does not match its RDF release."""


class RDFSmokeTestError(RDFProjectionError):
    """Raised when a candidate fails its smoke tests."""
