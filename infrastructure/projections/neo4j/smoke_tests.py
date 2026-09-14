"""Neo4j candidate smoke tests.

Run representative queries against a built candidate to verify:

* entities can be retrieved;
* relations can be traversed (both endpoints resolve);
* identifiers resolve (stored id matches the node id);
* provenance can be accessed where the profile requires it.

Smoke tests operate on the candidate only and never on the active
projection.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.neo4j.builder import ExpectedProjection
from infrastructure.projections.neo4j.client import Neo4jClient
from infrastructure.projections.neo4j.schema import (
    PROP_ACTIVITY_ID,
    PROP_AGENT_ID,
    PROP_ASSERTED_AT,
    PROP_ID,
    neo4j_candidate_name,
)


class Neo4jSmokeTestResult(BaseModel):
    """Outcome of the candidate smoke tests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_retrieval: bool = False
    relation_traversal: bool = False
    identifier_resolution: bool = False
    provenance_access: bool = False
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every smoke check succeeded."""
        return (
            self.entity_retrieval
            and self.relation_traversal
            and self.identifier_resolution
            and self.provenance_access
        )


class Neo4jSmokeTestRunner:
    """Runs representative queries against a built candidate."""

    def __init__(self, *, client: Neo4jClient) -> None:
        self._client = client

    def run(
        self,
        *,
        projection_id: str,
        expected: ExpectedProjection,
    ) -> Neo4jSmokeTestResult:
        """Run the smoke tests against the candidate."""
        store_key = neo4j_candidate_name(projection_id)
        errors: list[str] = []

        entity_retrieval = self._check_entity_retrieval(store_key, expected, errors)
        relation_traversal = self._check_relation_traversal(store_key, errors)
        identifier_resolution = self._check_identifier_resolution(store_key, errors)
        provenance_access = self._check_provenance_access(store_key, expected, errors)

        return Neo4jSmokeTestResult(
            entity_retrieval=entity_retrieval,
            relation_traversal=relation_traversal,
            identifier_resolution=identifier_resolution,
            provenance_access=provenance_access,
            errors=tuple(errors),
        )

    def _check_entity_retrieval(
        self,
        store_key: str,
        expected: ExpectedProjection,
        errors: list[str],
    ) -> bool:
        missing = sorted(
            entity.id
            for entity in expected.entities
            if self._client.get_node(store_key, entity.id) is None
        )
        if missing:
            errors.append(f"entities could not be retrieved: {missing}")
            return False
        return True

    def _check_relation_traversal(
        self,
        store_key: str,
        errors: list[str],
    ) -> bool:
        relationships = self._client.all_relationships(store_key)
        if not relationships:
            return True
        dangling = sorted(
            relationship.id
            for relationship in relationships
            if self._client.get_node(store_key, relationship.start_node_id) is None
            or self._client.get_node(store_key, relationship.end_node_id) is None
        )
        if dangling:
            errors.append(f"relations with missing endpoints: {dangling}")
            return False
        return True

    def _check_identifier_resolution(
        self,
        store_key: str,
        errors: list[str],
    ) -> bool:
        mismatched = sorted(
            node.id
            for node in self._client.all_nodes(store_key)
            if node.properties.get(PROP_ID, node.id) != node.id
        )
        if mismatched:
            errors.append(f"identifier mismatches: {mismatched}")
            return False
        return True

    def _check_provenance_access(
        self,
        store_key: str,
        expected: ExpectedProjection,
        errors: list[str],
    ) -> bool:
        required = [
            relationship
            for relationship in expected.relationships
            if relationship.agent_id is not None
        ]
        relationships = {
            relationship.id: relationship
            for relationship in self._client.all_relationships(store_key)
        }
        for expected_rel in required:
            stored = relationships.get(expected_rel.assertion_id)
            if stored is None:
                continue
            properties = stored.properties
            if (
                properties.get(PROP_AGENT_ID) != expected_rel.agent_id
                or properties.get(PROP_ACTIVITY_ID) != expected_rel.activity_id
                or properties.get(PROP_ASSERTED_AT) != expected_rel.asserted_at
            ):
                errors.append(f"provenance inaccessible for {expected_rel.assertion_id}")
                return False
        return True
