"""In-memory projection backend.

Technology implementation conforming to the canonical ProjectionBackend protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts.projections import ProjectionBackend
from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import ProjectedRecord, ProjectionReconciler
from core.projection.result import ProjectionResult, ProjectionValidationResult
from core.projections.content import ProjectionContent

if TYPE_CHECKING:
    from infrastructure.projections.rdf.builder import RDFDataSource


class MemoryProjectionBackend:
    """Deterministic in-memory store for projections conforming to canonical ProjectionBackend.

    Maintains candidate, active, and retained projection states in memory.
    Also retains legacy write/read/delete methods for backward compatibility.
    """

    def __init__(
        self,
        *,
        data_source: RDFDataSource | None = None,
        backend_id: str = "memory",
    ) -> None:
        self.backend_id = backend_id
        self._data_source = data_source
        self._legacy_store: dict[str, ProjectionContent] = {}
        self._candidate_records: dict[str, tuple[ProjectedRecord, ...]] = {}
        self._active_records: dict[str, tuple[ProjectedRecord, ...]] = {}
        self._retained_records: dict[str, tuple[ProjectedRecord, ...]] = {}
        self._projects: dict[str, tuple[str, ProjectionProfile]] = {}

    def set_data_source(self, data_source: RDFDataSource) -> None:
        """Set or update the active RDFDataSource."""
        self._data_source = data_source

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        """Build candidate in-memory projection from authoritative RDF dataset."""
        records: tuple[ProjectedRecord, ...] = ()
        if self._data_source is not None:
            dataset = self._data_source.get(release_id)
            if dataset is not None:
                records = ProjectionReconciler().authoritative_records(dataset)

        self._candidate_records[projection_id] = records
        self._projects[projection_id] = (release_id, profile)
        return ProjectionResult(
            projection_id=projection_id,
            backend_id=self.backend_id,
            message="in-memory projection built",
            record_count=len(records),
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate projection in memory."""
        if projection_id not in self._candidate_records:
            return ProjectionValidationResult(
                projection_id=projection_id,
                passed=False,
                errors=("no candidate projection found in memory",),
            )
        return ProjectionValidationResult(
            projection_id=projection_id,
            passed=True,
            errors=(),
        )

    def records(
        self,
        projection_id: str,
    ) -> tuple[ProjectedRecord, ...]:
        """Report records currently stored for candidate projection_id."""
        return self._candidate_records.get(projection_id, ())

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Promote candidate records to active and retain previous active."""
        if projection_id in self._active_records:
            self._retained_records[projection_id] = self._active_records[projection_id]
        if projection_id in self._candidate_records:
            self._active_records[projection_id] = self._candidate_records[projection_id]

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back active records to retained state."""
        if projection_id in self._retained_records:
            self._active_records[projection_id] = self._retained_records[projection_id]

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy all candidate, active, and retained records for projection_id."""
        self._candidate_records.pop(projection_id, None)
        self._active_records.pop(projection_id, None)
        self._retained_records.pop(projection_id, None)
        self._projects.pop(projection_id, None)
        self._legacy_store.pop(projection_id, None)

    # --- Legacy methods for backward compatibility ---
    def write(self, content: ProjectionContent) -> None:
        self._legacy_store[content.projection_id.canonical] = content

    def read(self, projection_id: str) -> ProjectionContent | None:
        return self._legacy_store.get(projection_id)

    def delete(self, projection_id: str) -> None:
        self._legacy_store.pop(projection_id, None)


def conforms_to_backend(backend: object) -> bool:
    """True when backend implements canonical ProjectionBackend protocol."""
    return isinstance(backend, ProjectionBackend)
