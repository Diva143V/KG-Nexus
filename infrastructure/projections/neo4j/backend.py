"""Neo4jProjectionBackend: the first concrete ProjectionBackend.

Neo4j is a derived projection: RDF remains authoritative. This backend
implements the Phase 13 ``ProjectionBackend`` contract and is registered
through ``ProjectionRegistry``. Core never imports it and never knows it is
Neo4j.

Lifecycle within the backend:

    BUILD (candidate) -> VALIDATE -> RECONCILE -> SMOKE TEST -> READY

and activation is atomic: the candidate is promoted to active while the
previous active projection is retained for rollback (its content is never
deleted before activation).
"""

from __future__ import annotations

from hashlib import sha256

from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import ProjectedRecord
from core.projection.result import ProjectionResult, ProjectionValidationResult
from infrastructure.projections.neo4j.builder import Neo4jProjectionBuilder, RDFDataSource
from infrastructure.projections.neo4j.client import Neo4jClient
from infrastructure.projections.neo4j.errors import UnknownNeo4jProjectionError
from infrastructure.projections.neo4j.reconciler import (
    Neo4jReconciler,
    Neo4jReconciliationReport,
)
from infrastructure.projections.neo4j.schema import (
    ATTR_ASSERTION,
    ATTR_PREDICATE,
    ATTR_VALUE,
    PROP_AGENT_ID,
    PROP_ASSERTION_IRI,
    PROP_OBJECT_IRI,
    PROP_PREDICATE,
    PROP_SUBJECT_IRI,
    identifier_from_iri,
    identifier_iri,
    neo4j_candidate_name,
    safe_key,
)
from infrastructure.projections.neo4j.smoke_tests import (
    Neo4jSmokeTestResult,
    Neo4jSmokeTestRunner,
)


class Neo4jProjectionBackend:
    """Concrete ProjectionBackend that stores projections in Neo4j.

    ``data_source`` supplies the authoritative RDF release the backend builds
    from. In production this reads from ``RDFAuthority``; tests inject an
    in-memory source. ``client`` is where a real Neo4j driver plugs in.
    """

    def __init__(
        self,
        *,
        client: Neo4jClient,
        data_source: RDFDataSource,
        backend_id: str = "neo4j",
        builder: Neo4jProjectionBuilder | None = None,
        reconciler: Neo4jReconciler | None = None,
        smoke_tests: Neo4jSmokeTestRunner | None = None,
    ) -> None:
        self.backend_id = backend_id
        self._client = client
        self._data_source = data_source
        self._builder = builder or Neo4jProjectionBuilder(
            client=client,
            data_source=data_source,
        )
        self._reconciler = reconciler or Neo4jReconciler(
            client=client,
            data_source=data_source,
        )
        self._smoke_tests = smoke_tests or Neo4jSmokeTestRunner(client=client)
        self._projects: dict[str, tuple[str, ProjectionProfile]] = {}

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        """Build a candidate projection from the authoritative RDF release."""
        record_count = self._builder.build(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        self._projects[projection_id] = (release_id, profile)
        return ProjectionResult(
            projection_id=projection_id,
            backend_id=self.backend_id,
            message="candidate projection built",
            record_count=record_count,
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate: structure, reconciliation, and smoke tests.

        A candidate is only valid if it matches the RDF release exactly and
        passes smoke tests. Failed candidates are reported, never activated.
        """
        release_id, profile = self._require(projection_id)
        errors: list[str] = []

        structural = self._structural_errors(projection_id, release_id, profile)
        errors.extend(structural)

        report = self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        if not report.reconciled:
            errors.append(f"reconciliation: {self._report_summary(report)}")

        expected = self._builder.derive(release_id, profile)
        smoke = self._smoke_tests.run(projection_id=projection_id, expected=expected)
        if not smoke.passed:
            errors.append(f"smoke tests: {'; '.join(smoke.errors)}")

        return ProjectionValidationResult(
            projection_id=projection_id,
            passed=not errors,
            errors=tuple(errors),
        )

    def records(
        self,
        projection_id: str,
    ) -> tuple[ProjectedRecord, ...]:
        """Backend-neutral records for the candidate, in Core's canonical form.

        Core treats the subjects of assertions as its entity records. The
        candidate materializes every referenced identifier as a node (the
        entity graph), so ``records`` reports entity records only for nodes
        that are assertion subjects — keeping the Core-facing view identical
        to the authoritative RDF derivation.
        """
        self._require(projection_id)
        store_key = neo4j_candidate_name(projection_id)
        records: list[ProjectedRecord] = []

        nodes = {node.id: node for node in self._client.all_nodes(store_key)}
        relationships = self._client.all_relationships(store_key)

        subject_identifiers = {
            identifier_from_iri(rel.properties[PROP_SUBJECT_IRI]) for rel in relationships
        }
        subject_identifiers.update(
            node.id
            for node in nodes.values()
            if any(key.startswith(f"{ATTR_VALUE}_") for key in node.properties)
        )

        for node in nodes.values():
            if node.id not in subject_identifiers:
                continue
            iri = identifier_iri(node.id)
            records.append(
                ProjectedRecord(
                    kind="entity",
                    key=iri,
                    digest=digest(iri),
                )
            )

        for relationship in relationships:
            properties = relationship.properties
            assertion_iri = properties[PROP_ASSERTION_IRI]
            predicate = properties[PROP_PREDICATE]
            object_iri = properties[PROP_OBJECT_IRI]
            records.append(
                ProjectedRecord(
                    kind="assertion",
                    key=assertion_iri,
                    digest=digest(predicate),
                )
            )
            records.append(
                ProjectedRecord(
                    kind="relation",
                    key=f"{assertion_iri}:urn:assertion:object:{object_iri}",
                    digest=digest(f"{assertion_iri}:{object_iri}"),
                )
            )

        for node in nodes.values():
            records.extend(attribute_records(node.properties))

        return tuple(records)

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Atomically promote the candidate to active."""
        self._require(projection_id)
        self._client.activate(neo4j_candidate_name(projection_id))

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection; retained content stays untouched."""
        self._require(projection_id)
        self._client.rollback(neo4j_candidate_name(projection_id))

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection's content, if present."""
        self._client.delete_projection(neo4j_candidate_name(projection_id))
        self._projects.pop(projection_id, None)

    def reconcile(
        self,
        projection_id: str,
    ) -> Neo4jReconciliationReport:
        """Neo4j-specific reconciliation report for the candidate."""
        release_id, profile = self._require(projection_id)
        return self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )

    def smoke_test(
        self,
        projection_id: str,
    ) -> Neo4jSmokeTestResult:
        """Smoke test report for the candidate."""
        release_id, profile = self._require(projection_id)
        expected = self._builder.derive(release_id, profile)
        return self._smoke_tests.run(projection_id=projection_id, expected=expected)

    def _structural_errors(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> list[str]:
        expected = self._builder.derive(release_id, profile)
        store_key = neo4j_candidate_name(projection_id)
        errors: list[str] = []

        node_count = self._client.node_count(store_key)
        if node_count != len(expected.entities):
            errors.append(f"expected entity count {len(expected.entities)}, found {node_count}")
        missing_ids = sorted(
            entity.id
            for entity in expected.entities
            if self._client.get_node(store_key, entity.id) is None
        )
        if missing_ids:
            errors.append(f"required identifiers missing: {missing_ids}")

        relationship_count = self._client.relationship_count(store_key)
        if relationship_count != len(expected.relationships):
            errors.append(
                f"expected relationship count {len(expected.relationships)}, "
                f"found {relationship_count}"
            )

        for relationship in expected.relationships:
            stored = self._client.get_relationship(store_key, relationship.assertion_id)
            if stored is None:
                errors.append(f"assertion missing: {relationship.assertion_id}")
                continue
            if (
                relationship.agent_id is not None
                and stored.properties.get(PROP_AGENT_ID) != relationship.agent_id
            ):
                errors.append(f"required provenance missing on {relationship.assertion_id}")

        for attribute in expected.attributes:
            node = self._client.get_node(store_key, attribute.subject)
            if (
                node is None
                or node.properties.get(f"{ATTR_VALUE}_{safe_key(attribute.predicate)}")
                != attribute.value
            ):
                errors.append(f"assertion missing: {attribute.assertion_id}")

        return errors

    def _require(self, projection_id: str) -> tuple[str, ProjectionProfile]:
        entry = self._projects.get(projection_id)
        if entry is None:
            raise UnknownNeo4jProjectionError(projection_id)
        return entry

    @staticmethod
    def _report_summary(report: Neo4jReconciliationReport) -> str:
        parts = [
            f"missing_entities={len(report.missing_entities)}",
            f"unexpected_entities={len(report.unexpected_entities)}",
            f"missing_relations={len(report.missing_relations)}",
            f"unexpected_relations={len(report.unexpected_relations)}",
            f"identifier_mismatches={len(report.identifier_mismatches)}",
            f"assertion_mismatches={len(report.assertion_mismatches)}",
        ]
        return ", ".join(parts)


def attribute_records(properties: dict[str, str]) -> tuple[ProjectedRecord, ...]:
    """Backend-neutral assertion records for attribute assertions on a node."""
    records: list[ProjectedRecord] = []
    prefix = f"{ATTR_VALUE}_"
    for key in properties:
        if not key.startswith(prefix):
            continue
        safe = key[len(prefix) :]
        assertion_iri = properties.get(f"{ATTR_ASSERTION}_{safe}")
        predicate = properties.get(f"{ATTR_PREDICATE}_{safe}")
        if assertion_iri is None or predicate is None:
            continue
        records.append(
            ProjectedRecord(
                kind="assertion",
                key=assertion_iri,
                digest=digest(predicate),
            )
        )
    return tuple(records)


def digest(value: str) -> str:
    """Stable sha256 hex digest matching Core's canonical record digest."""
    return sha256(value.encode("utf-8")).hexdigest()
