"""ProjectionReconciler: verify a projection matches its authoritative RDF."""

from __future__ import annotations

from enum import StrEnum

from core.identifiers.identifier import Identifier
from core.rdf.graph import RDFDataset
from infrastructure.projections.legacy_framework.builder import ProjectionBuilder
from infrastructure.projections.legacy_framework.content import ProjectionContent
from infrastructure.projections.legacy_framework.profile import (
    ProjectionProfile,
    ReconciliationMethod,
)


class ReconciliationOutcome(StrEnum):
    """Whether a projection reconciled with the authoritative RDF."""

    RECONCILED = "reconciled"
    DRIFTED = "drifted"


class ReconciliationResult:
    """Outcome of reconciling a projection against the authoritative RDF."""

    def __init__(self, outcome: ReconciliationOutcome, detail: str) -> None:
        self.outcome = outcome
        self.detail = detail

    @property
    def reconciled(self) -> bool:
        return self.outcome is ReconciliationOutcome.RECONCILED


class ProjectionReconciler:
    """Checks a projection against the authoritative RDF dataset.

    Reconciliation rebuilds the projection from the RDF source (never the
    other way around) and compares per the profile's declared method.
    """

    def __init__(self, builder: ProjectionBuilder | None = None) -> None:
        self._builder = builder or ProjectionBuilder()

    def reconcile(
        self,
        *,
        projection_id: Identifier,
        dataset: RDFDataset,
        content: ProjectionContent,
        profile: ProjectionProfile,
    ) -> ReconciliationResult:
        """Reconcile ``content`` by rebuilding from ``dataset``."""
        rebuilt = self._builder.build(
            projection_id=projection_id,
            dataset=dataset,
            profile=profile,
        )
        if profile.reconciliation_method is ReconciliationMethod.REBUILD:
            return self._compare(rebuilt, content, "rebuild")
        if profile.reconciliation_method is ReconciliationMethod.DIGEST:
            return self._compare_digest(rebuilt, content)
        if profile.reconciliation_method is ReconciliationMethod.ROW_BY_ROW:
            return self._compare_rows(rebuilt, content)
        raise ValueError(f"unknown reconciliation method: {profile.reconciliation_method}")

    @staticmethod
    def _compare(
        rebuilt: ProjectionContent,
        content: ProjectionContent,
        method: str,
    ) -> ReconciliationResult:
        if rebuilt == content:
            return ReconciliationResult(
                ReconciliationOutcome.RECONCILED, f"{method}: projections match"
            )
        return ReconciliationResult(
            ReconciliationOutcome.DRIFTED,
            f"{method}: projection differs from authoritative RDF",
        )

    @staticmethod
    def _compare_digest(
        rebuilt: ProjectionContent,
        content: ProjectionContent,
    ) -> ReconciliationResult:
        if rebuilt.digest == content.digest:
            return ReconciliationResult(
                ReconciliationOutcome.RECONCILED, "digest: projections match"
            )
        return ReconciliationResult(
            ReconciliationOutcome.DRIFTED, "digest: projection digest differs"
        )

    @staticmethod
    def _compare_rows(
        rebuilt: ProjectionContent,
        content: ProjectionContent,
    ) -> ReconciliationResult:
        if (
            rebuilt.nodes == content.nodes
            and rebuilt.edges == content.edges
            and rebuilt.dropped_semantics == content.dropped_semantics
            and rebuilt.unsupported_semantics == content.unsupported_semantics
        ):
            return ReconciliationResult(
                ReconciliationOutcome.RECONCILED, "row-by-row: projections match"
            )
        return ReconciliationResult(
            ReconciliationOutcome.DRIFTED,
            "row-by-row: node/edge rows differ from authoritative RDF",
        )
