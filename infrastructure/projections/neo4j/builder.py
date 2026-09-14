"""Neo4j projection builder: RDF release -> candidate projection.

RDF remains authoritative. The builder reads the approved assertion graph
and the provenance graph from the RDF release and materializes a complete
candidate in the Neo4j-like store. The candidate is always built under its
own distinct store key — never into the active projection.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from core.rdf.graph import NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import IRI, BlankNode, RDFLiteral, Triple
from core.rdf.writer import (
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_STATE,
    ASN_SUBJECT,
    ASN_VALUE,
    PROV_ACTIVITY,
    PROV_AGENT,
    PROV_ASSERTED_AT,
    PROV_METHOD,
)
from infrastructure.projections.neo4j.client import Neo4jClient
from infrastructure.projections.neo4j.errors import MissingRDFReleaseError, Neo4jProjectionError
from infrastructure.projections.neo4j.schema import (
    Neo4jNode,
    assertion_id_from_iri,
    attribute_properties,
    entity_node,
    identifier_from_iri,
    namespace_of,
    neo4j_candidate_name,
    relationship_for,
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


class ExpectedEntity(BaseModel):
    """A projected entity, in backend-neutral terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)

    @property
    def iri(self) -> str:
        return f"urn:identifier:{self.id}"


class ExpectedRelationship(BaseModel):
    """A relationship assertion derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    object: str = Field(min_length=1)
    state: str = Field(min_length=1)
    agent_id: str | None = None
    activity_id: str | None = None
    asserted_at: str | None = None
    method: str | None = None

    @property
    def assertion_iri(self) -> str:
        return f"urn:assertion:{self.assertion_id}"

    @property
    def subject_iri(self) -> str:
        return f"urn:identifier:{self.subject}"

    @property
    def object_iri(self) -> str:
        return f"urn:identifier:{self.object}"


class ExpectedAttribute(BaseModel):
    """An attribute assertion derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    value: str = Field(min_length=1)
    state: str = Field(min_length=1)
    agent_id: str | None = None
    activity_id: str | None = None
    asserted_at: str | None = None
    method: str | None = None

    @property
    def assertion_iri(self) -> str:
        return f"urn:assertion:{self.assertion_id}"


class ExpectedProjection(BaseModel):
    """The full expected projection content, derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entities: tuple[ExpectedEntity, ...] = Field(default_factory=tuple)
    relationships: tuple[ExpectedRelationship, ...] = Field(default_factory=tuple)
    attributes: tuple[ExpectedAttribute, ...] = Field(default_factory=tuple)

    @property
    def assertion_count(self) -> int:
        """Total number of assertions (relationships + attributes)."""
        return len(self.relationships) + len(self.attributes)


class Neo4jProjectionBuilder:
    """Builds complete candidate projections from an authoritative RDF release."""

    def __init__(
        self,
        *,
        client: Neo4jClient,
        data_source: RDFDataSource,
    ) -> None:
        self._client = client
        self._data_source = data_source

    def derive(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ExpectedProjection:
        """Derive the expected projection from the RDF release."""
        dataset = self._data_source.get(release_id)
        if dataset is None:
            raise MissingRDFReleaseError(release_id)
        relationships, attributes, entities = self._parse(dataset)
        return self._apply_profile(relationships, attributes, entities, profile)

    def build(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> int:
        """Build a candidate projection from the RDF release.

        Returns the number of projected records (entities + relationships).
        The candidate is built under its own store key and never touches the
        active projection.
        """
        store_key = neo4j_candidate_name(projection_id)
        if self._client.has_projection(store_key):
            raise Neo4jProjectionError(f"candidate already exists for projection: {projection_id}")
        expected = self.derive(release_id, profile)

        nodes: dict[str, Neo4jNode] = {
            entity.id: entity_node(entity.id) for entity in expected.entities
        }
        for attribute in expected.attributes:
            node = nodes[attribute.subject]
            properties = dict(node.properties)
            properties.update(
                attribute_properties(
                    assertion_id=attribute.assertion_id,
                    predicate=attribute.predicate,
                    value=attribute.value,
                    state=attribute.state,
                    agent_id=attribute.agent_id,
                    activity_id=attribute.activity_id,
                    asserted_at=attribute.asserted_at,
                    method=attribute.method,
                )
            )
            nodes[attribute.subject] = node.model_copy(update={"properties": properties})

        for node in sorted(nodes.values(), key=lambda n: n.id):
            self._client.create_node(store_key, node)
        for relationship in expected.relationships:
            self._client.create_relationship(
                store_key,
                relationship_for(
                    assertion_id=relationship.assertion_id,
                    predicate=relationship.predicate,
                    subject=relationship.subject,
                    object=relationship.object,
                    state=relationship.state,
                    agent_id=relationship.agent_id,
                    activity_id=relationship.activity_id,
                    asserted_at=relationship.asserted_at,
                    method=relationship.method,
                ),
            )
        return len(nodes) + len(expected.relationships)

    def _parse(
        self,
        dataset: RDFDataset,
    ) -> tuple[list[ExpectedRelationship], list[ExpectedAttribute], set[str]]:
        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        provenance = dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))

        assertion_triples: dict[str, dict[str, Triple]] = {}
        if approved is not None:
            for triple in approved.triples:
                subject = _term_value(triple.subject)
                bucket = assertion_triples.setdefault(subject, {})
                bucket[triple.predicate.value] = triple

        provenance_map: dict[str, dict[str, str]] = {}
        if provenance is not None:
            for triple in provenance.triples:
                subject = _term_value(triple.subject)
                provenance_map.setdefault(subject, {})[triple.predicate.value] = _term_value(
                    triple.object
                )

        relationships: list[ExpectedRelationship] = []
        attributes: list[ExpectedAttribute] = []
        entities: set[str] = set()

        for node, triples in assertion_triples.items():
            if ASN_STATE not in triples:
                continue
            state = _term_value(triples[ASN_STATE].object)
            subject = identifier_from_iri(_term_value(triples[ASN_SUBJECT].object))
            predicate = _term_value(triples[ASN_PREDICATE].object)
            entities.add(subject)
            prov = provenance_map.get(node, {})
            agent_id = _maybe_identifier(prov.get(PROV_AGENT))
            activity_id = _maybe_identifier(prov.get(PROV_ACTIVITY))
            asserted_at = prov.get(PROV_ASSERTED_AT)

            if ASN_OBJECT in triples:
                obj = identifier_from_iri(_term_value(triples[ASN_OBJECT].object))
                entities.add(obj)
                relationships.append(
                    ExpectedRelationship(
                        assertion_id=assertion_id_from_iri(node),
                        predicate=predicate,
                        subject=subject,
                        object=obj,
                        state=state,
                        agent_id=agent_id,
                        activity_id=activity_id,
                        asserted_at=asserted_at,
                        method=prov.get(PROV_METHOD),
                    )
                )
            elif ASN_VALUE in triples:
                attributes.append(
                    ExpectedAttribute(
                        assertion_id=assertion_id_from_iri(node),
                        predicate=predicate,
                        subject=subject,
                        value=_term_value(triples[ASN_VALUE].object),
                        state=state,
                        agent_id=agent_id,
                        activity_id=activity_id,
                        asserted_at=asserted_at,
                        method=prov.get(PROV_METHOD),
                    )
                )
        return relationships, attributes, entities

    @staticmethod
    def _apply_profile(
        relationships: list[ExpectedRelationship],
        attributes: list[ExpectedAttribute],
        entities: set[str],
        profile: ProjectionProfile,
    ) -> ExpectedProjection:
        included_relations = set(profile.included_relations)
        included_types = set(profile.included_entity_types)

        def keep_entity(entity_id: str) -> bool:
            if not included_types:
                return True
            return namespace_of(entity_id) in included_types

        if included_relations:
            relationships = [r for r in relationships if r.predicate in included_relations]
            attributes = [a for a in attributes if a.predicate in included_relations]
        relationships = [
            r for r in relationships if keep_entity(r.subject) and keep_entity(r.object)
        ]
        attributes = [a for a in attributes if keep_entity(a.subject)]
        entities = {e for e in entities if keep_entity(e)}

        return ExpectedProjection(
            entities=tuple(sorted((ExpectedEntity(id=e) for e in entities), key=lambda e: e.id)),
            relationships=tuple(sorted(relationships, key=lambda r: r.assertion_id)),
            attributes=tuple(sorted(attributes, key=lambda a: a.assertion_id)),
        )


def _term_value(term: IRI | BlankNode | RDFLiteral) -> str:
    if isinstance(term, RDFLiteral):
        return term.value
    if isinstance(term, IRI):
        return term.value
    return f"_:{term.label}"


def _maybe_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return identifier_from_iri(value)
