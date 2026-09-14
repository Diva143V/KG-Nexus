"""Neo4j candidate reconciliation against the authoritative RDF release.

RDF is authoritative. The reconciler compares the Neo4j candidate against
the expected projection derived from the RDF release and reports, in
Neo4j-visible terms:

* missing / unexpected entities
* missing / unexpected relations
* identifier mismatches
* assertion mismatches

Data loss is never silently accepted: any divergence is reported.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from infrastructure.projections.neo4j.builder import (
    ExpectedProjection,
    ExpectedRelationship,
    Neo4jProjectionBuilder,
    RDFDataSource,
)
from infrastructure.projections.neo4j.client import Neo4jClient
from infrastructure.projections.neo4j.schema import (
    ATTR_VALUE,
    PROP_ACTIVITY_ID,
    PROP_AGENT_ID,
    PROP_ASSERTED_AT,
    PROP_ASSERTION_IRI,
    PROP_ID,
    PROP_OBJECT_IRI,
    PROP_PREDICATE,
    PROP_STATE,
    PROP_SUBJECT_IRI,
    Neo4jRelationship,
    neo4j_candidate_name,
    safe_key,
)


class Neo4jReconciliationReport(BaseModel):
    """Outcome of reconciling one Neo4j candidate against its RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    missing_entities: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_entities: tuple[str, ...] = Field(default_factory=tuple)
    missing_relations: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_relations: tuple[str, ...] = Field(default_factory=tuple)
    identifier_mismatches: tuple[str, ...] = Field(default_factory=tuple)
    assertion_mismatches: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def reconciled(self) -> bool:
        """True when the candidate matches the RDF release exactly."""
        return not (
            self.missing_entities
            or self.unexpected_entities
            or self.missing_relations
            or self.unexpected_relations
            or self.identifier_mismatches
            or self.assertion_mismatches
        )


class Neo4jReconciler:
    """Reconciles a Neo4j candidate against the authoritative RDF release."""

    def __init__(
        self,
        *,
        client: Neo4jClient,
        data_source: RDFDataSource,
        builder: Neo4jProjectionBuilder | None = None,
    ) -> None:
        self._client = client
        self._data_source = data_source
        self._builder = builder or Neo4jProjectionBuilder(
            client=client,
            data_source=data_source,
        )

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> Neo4jReconciliationReport:
        """Compare the candidate under ``projection_id`` against the RDF release."""
        expected = self._builder.derive(release_id, profile)
        store_key = neo4j_candidate_name(projection_id)

        nodes = self._client.all_nodes(store_key)
        relationships = self._client.all_relationships(store_key)

        actual_entities = {node.id for node in nodes}
        expected_entities = {entity.id for entity in expected.entities}
        missing_entities = sorted(expected_entities - actual_entities)
        unexpected_entities = sorted(actual_entities - expected_entities)

        actual_relations = {rel.id for rel in relationships}
        expected_relations = {rel.assertion_id for rel in expected.relationships}
        missing_relations = sorted(expected_relations - actual_relations)
        unexpected_relations = sorted(actual_relations - expected_relations)

        identifier_mismatches = sorted(
            node.id for node in nodes if node.properties.get(PROP_ID, node.id) != node.id
        )

        assertion_mismatches = sorted(
            relation.id
            for relation in relationships
            if relation.id in expected_relations and not _matches(relation, expected.relationships)
        )
        assertion_mismatches.extend(self._attribute_mismatches(store_key, expected))

        return Neo4jReconciliationReport(
            projection_id=projection_id,
            release_id=release_id,
            missing_entities=tuple(missing_entities),
            unexpected_entities=tuple(unexpected_entities),
            missing_relations=tuple(missing_relations),
            unexpected_relations=tuple(unexpected_relations),
            identifier_mismatches=tuple(identifier_mismatches),
            assertion_mismatches=tuple(sorted(set(assertion_mismatches))),
        )

    def _attribute_mismatches(
        self,
        store_key: str,
        expected: ExpectedProjection,
    ) -> list[str]:
        mismatches: list[str] = []
        for attribute in expected.attributes:
            node = self._client.get_node(store_key, attribute.subject)
            key = f"{ATTR_VALUE}_{safe_key(attribute.predicate)}"
            if node is None or node.properties.get(key) != attribute.value:
                mismatches.append(attribute.assertion_id)
        return mismatches


def _matches(
    relationship: Neo4jRelationship,
    expected: tuple[ExpectedRelationship, ...],
) -> bool:
    for candidate in expected:
        if candidate.assertion_id != relationship.id:
            continue
        props = relationship.properties
        if props.get(PROP_PREDICATE) != candidate.predicate:
            return False
        if props.get(PROP_STATE) != candidate.state:
            return False
        if props.get(PROP_ASSERTION_IRI) != candidate.assertion_iri:
            return False
        if props.get(PROP_SUBJECT_IRI) != candidate.subject_iri:
            return False
        if props.get(PROP_OBJECT_IRI) != candidate.object_iri:
            return False
        if props.get(PROP_AGENT_ID) != candidate.agent_id:
            return False
        if props.get(PROP_ACTIVITY_ID) != candidate.activity_id:
            return False
        if props.get(PROP_ASSERTED_AT) != candidate.asserted_at:
            return False
        return True
    return False
