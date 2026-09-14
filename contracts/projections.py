"""Canonical contracts and protocols for projection backends and manifests.

Defines the dependency-free boundary for projection backends, lifecycle protocols,
and manifest metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from core.projection.profile import ProjectionProfile
    from core.projection.reconciliation import ProjectedRecord
    from core.projection.result import ProjectionResult, ProjectionValidationResult


@runtime_checkable
class ProjectionBackend(Protocol):
    """Generic interface for every downstream projection backend.

    Guarantees:
    - No backend-specific concepts.
    - No graph-database or storage technology leaks.
    - Clear lifecycle hooks: build, validate, records, activate, rollback, destroy.
    """

    @property
    def backend_id(self) -> str:
        """Stable identifier for this backend (e.g. 'rdf', 'parquet', 'neo4j', 'memory')."""
        ...

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        """Build a candidate projection for ``release_id`` per ``profile``."""
        ...

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate projection stored for ``projection_id``."""
        ...

    def records(
        self,
        projection_id: str,
    ) -> tuple[ProjectedRecord, ...]:
        """Report the records currently stored for ``projection_id`` in backend-neutral terms."""
        ...

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Atomically activate the projection for ``projection_id``."""
        ...

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection for ``projection_id`` to its retained state."""
        ...

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection for ``projection_id``, if present."""
        ...


class ProjectionManifestRecord(BaseModel):
    """Immutable record of a projection build, status, and digest metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    schema_version: str = Field(default="1.0.0")
    model_version: str | None = None
    input_digest: str = Field(min_length=1)
    output_digest: str = Field(min_length=1)
    record_count: int = Field(ge=0, default=0)
    manifest_json: str = Field(default="{}")
    created_at: str = Field(min_length=1)
    activated_at: str | None = None
