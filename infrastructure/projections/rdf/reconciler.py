"""RDF projection reconciliation against the authoritative RDF release.

RDF is authoritative. The reconciler compares the projected dataset against
the policy-derived expected dataset and reports, in deterministic string
terms:

* missing / unexpected graphs;
* missing / unexpected triples;
* transformed triples (same subject+predicate, different object).

Data loss is never silently accepted: any divergence is reported.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import Triple
from infrastructure.projections.rdf.builder import (
    RDFDataSource,
    RDFProjectionBuilder,
)
from infrastructure.projections.rdf.store import RDFProjectionStore, rdf_candidate_name
from infrastructure.projections.rdf.terms import canonical_triple, triple_key


class RDFReconciliationReport(BaseModel):
    """Outcome of reconciling one projected dataset against its release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    missing_graphs: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_graphs: tuple[str, ...] = Field(default_factory=tuple)
    missing_triples: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_triples: tuple[str, ...] = Field(default_factory=tuple)
    transformed_triples: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def reconciled(self) -> bool:
        """True when the projected dataset matches the expected dataset."""
        return not (
            self.missing_graphs
            or self.unexpected_graphs
            or self.missing_triples
            or self.unexpected_triples
            or self.transformed_triples
        )


class RDFReconciler:
    """Reconciles a projected dataset against the authoritative RDF release."""

    def __init__(
        self,
        *,
        store: RDFProjectionStore,
        data_source: RDFDataSource,
        builder: RDFProjectionBuilder | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._builder = builder or RDFProjectionBuilder(
            store=store,
            data_source=data_source,
        )

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> RDFReconciliationReport:
        """Compare the projected dataset against the expected dataset."""
        expected = self._builder.derive(release_id, profile)
        store_key = rdf_candidate_name(projection_id)
        actual = self._store.read_dataset(store_key)

        expected_graphs = {graph.name for graph in expected.graphs}
        actual_graphs = set(self._store.graph_names(store_key))
        missing_graphs = sorted(expected_graphs - actual_graphs)
        unexpected_graphs = sorted(actual_graphs - expected_graphs)

        missing_triples: list[str] = []
        unexpected_triples: list[str] = []
        for name in sorted(expected_graphs | actual_graphs):
            expected_triples = self._triples(expected.graph(name))
            actual_triples = self._triples(self._graph(actual, name))
            missing_triples.extend(
                f"{name}|{entry}" for entry in sorted(expected_triples - actual_triples)
            )
            unexpected_triples.extend(
                f"{name}|{entry}" for entry in sorted(actual_triples - expected_triples)
            )

        transformed = self._transformed(expected, actual)
        return RDFReconciliationReport(
            projection_id=projection_id,
            release_id=release_id,
            missing_graphs=tuple(missing_graphs),
            unexpected_graphs=tuple(unexpected_graphs),
            missing_triples=tuple(missing_triples),
            unexpected_triples=tuple(unexpected_triples),
            transformed_triples=tuple(sorted(transformed)),
        )

    def _transformed(self, expected: RDFDataset, actual: RDFDataset | None) -> list[str]:
        if actual is None:
            return []
        transformed: list[str] = []
        for name in sorted({graph.name for graph in expected.graphs}):
            expected_graph = expected.graph(name)
            actual_graph = actual.graph(name)
            if expected_graph is None or actual_graph is None:
                continue
            expected_by_s_p = self._by_subject_predicate(expected_graph.triples)
            actual_by_s_p = self._by_subject_predicate(actual_graph.triples)
            for key in sorted(expected_by_s_p.keys() & actual_by_s_p.keys()):
                if expected_by_s_p[key] != actual_by_s_p[key]:
                    subject, predicate = key.split("|", 1)
                    transformed.append(f"{name}|{subject}|{predicate}")
        return transformed

    @staticmethod
    def _by_subject_predicate(triples: tuple[Triple, ...]) -> dict[str, set[str]]:
        grouped: dict[str, set[str]] = {}
        for triple in triples:
            subject, predicate, _object = triple_key(triple)
            grouped.setdefault(f"{subject}|{predicate}", set()).add(_object)
        return grouped

    @staticmethod
    def _triples(graph: NamedGraph | None) -> set[str]:
        if graph is None:
            return set()
        return {canonical_triple(graph.name, triple) for triple in graph.triples}

    @staticmethod
    def _graph(dataset: RDFDataset | None, name: str) -> NamedGraph | None:
        if dataset is None:
            return None
        return dataset.graph(name)
