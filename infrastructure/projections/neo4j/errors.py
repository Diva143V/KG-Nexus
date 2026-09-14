"""Neo4j projection backend errors."""

from __future__ import annotations


class Neo4jProjectionError(Exception):
    """Base class for Neo4j projection errors."""


class Neo4jClientError(Neo4jProjectionError):
    """Raised when the Neo4j-like store rejects an operation."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class UnknownNeo4jProjectionError(Neo4jProjectionError):
    """Raised when operating on a projection the backend has not built."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        super().__init__(f"unknown Neo4j projection: {projection_id}")


class MissingRDFReleaseError(Neo4jProjectionError):
    """Raised when the authoritative RDF release is not available."""

    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        super().__init__(f"no RDF release available: {release_id}")


class Neo4jValidationError(Neo4jProjectionError):
    """Raised when a candidate projection fails structural validation."""

    def __init__(self, projection_id: str, reasons: tuple[str, ...]) -> None:
        self.projection_id = projection_id
        self.reasons = reasons
        super().__init__(
            f"Neo4j projection {projection_id} failed validation: " + "; ".join(reasons)
        )


class Neo4jReconciliationError(Neo4jProjectionError):
    """Raised when a candidate projection diverges from the RDF release."""

    def __init__(self, projection_id: str, detail: str) -> None:
        self.projection_id = projection_id
        self.detail = detail
        super().__init__(f"Neo4j projection {projection_id} failed reconciliation: {detail}")


class Neo4jSmokeTestError(Neo4jProjectionError):
    """Raised when candidate smoke tests fail."""

    def __init__(self, projection_id: str, detail: str) -> None:
        self.projection_id = projection_id
        self.detail = detail
        super().__init__(f"Neo4j projection {projection_id} failed smoke tests: {detail}")
