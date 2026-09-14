"""RDF projection builder: RDF release -> projected RDF dataset.

RDF remains authoritative. The builder reads a release's RDF dataset and
produces the projected dataset described by the profile policy: approved
assertions are filtered and transformed, supporting graphs and release
metadata are copied verbatim, and provenance is pruned to the assertions
that survive the projection. Output is always deterministically ordered.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile, UnsupportedBehavior
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import Triple, string_literal
from core.rdf.writer import (
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_SUBJECT,
    RDF_TYPE,
)
from infrastructure.projections.rdf.errors import (
    MissingRDFReleaseError,
    RDFProjectionError,
    RDFUnsupportedSemanticsError,
)
from infrastructure.projections.rdf.policy import RDFProjectionPolicy, policy_from_profile
from infrastructure.projections.rdf.store import RDFProjectionStore, rdf_candidate_name
from infrastructure.projections.rdf.terms import (
    canonical_triple,
    identifier_from_iri,
    namespace_of,
    term_key,
    term_value,
    triple_key,
)


class RDFDataSource(Protocol):
    """Provides the authoritative RDF release for a release id."""

    def get(self, release_id: str) -> RDFDataset | None:
        """Return the RDF dataset for ``release_id``, if available."""
        ...


class MemoryRDFDataSource:
    """In-memory RDFDataSource for tests and demos."""

    def __init__(self) -> None:
        self._datasets: dict[str, RDFDataset] = {}

    def put(self, release_id: str, dataset: RDFDataset) -> None:
        """Register an RDF dataset for ``release_id``."""
        self._datasets[release_id] = dataset

    def get(self, release_id: str) -> RDFDataset | None:
        return self._datasets.get(release_id)


class ExpectedAssertion(BaseModel):
    """An assertion node projected into the approved graph, in RDF terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_iri: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    subject_identifier: str = Field(min_length=1)
    object_identifier: str | None = None
    assertion_type: str = Field(min_length=1)

    @property
    def subject_iri(self) -> str:
        return f"urn:identifier:{self.subject_identifier}"

    @property
    def object_iri(self) -> str | None:
        if self.object_identifier is None:
            return None
        return f"urn:identifier:{self.object_identifier}"


class ExpectedRDFDataset(BaseModel):
    """The full expected projection content, derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: RDFDataset
    assertions: tuple[ExpectedAssertion, ...] = Field(default_factory=tuple)

    @property
    def assertion_count(self) -> int:
        """Number of approved assertions in the expected projection."""
        return len(self.assertions)


class RDFProjectionBuilder:
    """Builds complete projected RDF datasets from an authoritative release."""

    def __init__(
        self,
        *,
        store: RDFProjectionStore,
        data_source: RDFDataSource,
    ) -> None:
        self._store = store
        self._data_source = data_source

    def derive(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> RDFDataset:
        """Derive the projected dataset from the RDF release."""
        dataset = self._data_source.get(release_id)
        if dataset is None:
            raise MissingRDFReleaseError(release_id)
        policy = policy_from_profile(profile)

        approved_name = graph_name(NamedGraphCategory.APPROVED_ASSERTION)
        source_name = graph_name(NamedGraphCategory.SOURCE_ASSERTION)
        provenance_name = graph_name(NamedGraphCategory.PROVENANCE)

        approved = dataset.graph(approved_name)
        projected_approved = self._project_approved(approved, policy)

        projected: list[NamedGraph] = []
        for graph in dataset.graphs:
            if not policy.copies(graph.name):
                continue
            if graph.name == approved_name:
                if projected_approved is not None:
                    projected.append(projected_approved)
            elif graph.name == provenance_name:
                projected.append(
                    self._project_provenance(dataset, graph, policy, projected_approved)
                )
            elif graph.name == source_name:
                projected.append(graph)
            else:
                projected.append(graph)
        return RDFDataset(graphs=tuple(projected))

    def expected(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ExpectedRDFDataset:
        """Derive the expected projection with backend-neutral summaries."""
        dataset = self.derive(release_id, profile)
        approved_name = graph_name(NamedGraphCategory.APPROVED_ASSERTION)
        approved = dataset.graph(approved_name)
        if approved is None:
            return ExpectedRDFDataset(dataset=dataset)
        assertions: list[ExpectedAssertion] = []
        for _subject_key, triples in self._group(approved).items():
            by_predicate = {triple.predicate.value: triple for triple in triples}
            predicate = self._object_value(by_predicate.get(ASN_PREDICATE))
            subject_iri = self._object_value(by_predicate.get(ASN_SUBJECT))
            object_iri = self._object_value(by_predicate.get(ASN_OBJECT))
            assertion_type = self._object_value(by_predicate.get(RDF_TYPE))
            if predicate is None or subject_iri is None or assertion_type is None:
                continue
            assertions.append(
                ExpectedAssertion(
                    node_iri=term_value(triples[0].subject),
                    predicate=predicate,
                    subject_identifier=identifier_from_iri(subject_iri),
                    object_identifier=(
                        identifier_from_iri(object_iri) if object_iri is not None else None
                    ),
                    assertion_type=assertion_type,
                )
            )
        assertions.sort(key=lambda item: item.node_iri)
        return ExpectedRDFDataset(dataset=dataset, assertions=tuple(assertions))

    def build(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> int:
        """Build the projected dataset under the projection's candidate key.

        Returns the number of triples projected. The candidate is always
        written under its own distinct store key and never touches the
        active projection.
        """
        store_key = rdf_candidate_name(projection_id)
        if self._store.has_projection(store_key):
            raise RDFProjectionError(f"candidate already exists for projection: {projection_id}")
        dataset = self.derive(release_id, profile)
        self._store.write_dataset(store_key, dataset)
        return dataset.triple_count()

    def _project_approved(
        self,
        graph: NamedGraph | None,
        policy: RDFProjectionPolicy,
    ) -> NamedGraph | None:
        if graph is None:
            return None
        emitted: list[Triple] = []
        for _subject_key, triples in sorted(self._group(graph).items()):
            by_predicate = {triple.predicate.value: triple for triple in triples}
            predicate = self._object_value(by_predicate.get(ASN_PREDICATE))
            if predicate is None:
                continue
            if not self._included(predicate, by_predicate, policy):
                continue
            emitted.extend(self._emit(triples, predicate, policy))
        return NamedGraph(
            name=graph.name,
            triples=tuple(sorted(emitted, key=triple_key)),
        )

    def _included(
        self,
        predicate: str,
        by_predicate: dict[str, Triple],
        policy: RDFProjectionPolicy,
    ) -> bool:
        if policy.included_relations and predicate not in policy.included_relations:
            return False
        if predicate in policy.dropped_predicates:
            return False
        if predicate in policy.unsupported_semantics:
            if policy.unsupported_behavior is UnsupportedBehavior.ERROR:
                raise RDFUnsupportedSemanticsError(predicate, policy.profile_id)
            if policy.unsupported_behavior is UnsupportedBehavior.SKIP:
                return False
        assertion_type = self._object_value(by_predicate.get(RDF_TYPE))
        if (
            policy.included_assertion_types
            and assertion_type not in policy.included_assertion_types
        ):
            return False
        subject_iri = self._object_value(by_predicate.get(ASN_SUBJECT))
        if subject_iri is None:
            return False
        subject_id = identifier_from_iri(subject_iri)
        if (
            policy.included_entity_types
            and namespace_of(subject_id) not in policy.included_entity_types
        ):
            return False
        object_iri = self._object_value(by_predicate.get(ASN_OBJECT))
        if (
            object_iri is not None
            and policy.included_entity_types
            and namespace_of(identifier_from_iri(object_iri)) not in policy.included_entity_types
        ):
            return False
        return True

    @staticmethod
    def _emit(
        triples: list[Triple],
        predicate: str,
        policy: RDFProjectionPolicy,
    ) -> list[Triple]:
        target = policy.transformed_map.get(predicate)
        if target is None or target == predicate:
            return list(triples)
        emitted: list[Triple] = []
        for triple in triples:
            if triple.predicate.value == ASN_PREDICATE:
                emitted.append(
                    Triple(
                        subject=triple.subject,
                        predicate=triple.predicate,
                        object=string_literal(target),
                    )
                )
            else:
                emitted.append(triple)
        return emitted

    def _project_provenance(
        self,
        dataset: RDFDataset,
        graph: NamedGraph,
        policy: RDFProjectionPolicy,
        projected_approved: NamedGraph | None,
    ) -> NamedGraph:
        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        in_scope = {
            name
            for name, value in {
                graph_name(NamedGraphCategory.APPROVED_ASSERTION): projected_approved is not None,
                graph_name(NamedGraphCategory.SOURCE_ASSERTION): source is not None
                and policy.copies(graph_name(NamedGraphCategory.SOURCE_ASSERTION)),
            }.items()
            if value
        }
        projected_nodes = self._projected_assertion_nodes(
            in_scope,
            projected_approved,
            source,
        )
        release_nodes = self._release_assertion_nodes(approved, source)
        pruned = release_nodes - projected_nodes
        kept = [triple for triple in graph.triples if term_key(triple.subject) not in pruned]
        return NamedGraph(
            name=graph.name,
            triples=tuple(sorted(kept, key=triple_key)),
        )

    @staticmethod
    def _projected_assertion_nodes(
        in_scope: set[str],
        projected_approved: NamedGraph | None,
        source: NamedGraph | None,
    ) -> set[str]:
        nodes: set[str] = set()
        approved_name = graph_name(NamedGraphCategory.APPROVED_ASSERTION)
        source_name = graph_name(NamedGraphCategory.SOURCE_ASSERTION)
        if approved_name in in_scope and projected_approved is not None:
            nodes.update(term_key(triple.subject) for triple in projected_approved.triples)
        if source_name in in_scope and source is not None:
            nodes.update(term_key(triple.subject) for triple in source.triples)
        return nodes

    @staticmethod
    def _release_assertion_nodes(
        approved: NamedGraph | None,
        source: NamedGraph | None,
    ) -> set[str]:
        nodes: set[str] = set()
        if approved is not None:
            nodes.update(term_key(triple.subject) for triple in approved.triples)
        if source is not None:
            nodes.update(term_key(triple.subject) for triple in source.triples)
        return nodes

    @staticmethod
    def _group(graph: NamedGraph) -> dict[str, list[Triple]]:
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            by_subject.setdefault(term_key(triple.subject), []).append(triple)
        return by_subject

    @staticmethod
    def _object_value(triple: Triple | None) -> str | None:
        if triple is None:
            return None
        return term_value(triple.object)


def canonical(dataset: RDFDataset) -> tuple[str, ...]:
    """Deterministic string form of a full dataset, for comparisons."""
    entries: list[str] = []
    for graph in dataset.graphs:
        for triple in graph.triples:
            entries.append(canonical_triple(graph.name, triple))
    return tuple(sorted(entries))
