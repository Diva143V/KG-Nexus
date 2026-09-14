"""Parquet projection builder: RDF release -> analytical datasets.

RDF remains authoritative. The builder reads a release's RDF dataset and
materializes the analytical datasets described by the profile policy:
approved assertions are filtered and transformed (mirroring the documented
RDF copy/transform semantics), source assertions are copied verbatim with
their state, and provenance/evidence rows are pruned to the assertions that
survive. Output rows are always deterministically sorted, so identical
releases produce identical Parquet content.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile, UnsupportedBehavior
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import Triple
from core.rdf.writer import (
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_STATE,
    ASN_SUBJECT,
    ASN_TYPE_RELATIONSHIP,
    ASN_VALUE,
    EV_ARTIFACT,
    EV_EVIDENCE,
    EV_KIND,
    EV_OBTAINED_AT,
    EV_RECORD,
    PROV_ACTIVITY,
    PROV_AGENT,
    PROV_ASSERTED_AT,
    PROV_INPUT_ASSERTION,
    PROV_INPUT_RESOURCE,
    PROV_METHOD,
    RDF_TYPE,
)
from infrastructure.projections.parquet.datasets import (
    DATASET_COLUMNS,
    utc_naive_iso,
)
from infrastructure.projections.parquet.errors import (
    MissingParquetReleaseError,
    ParquetProjectionError,
    ParquetUnsupportedSemanticsError,
)
from infrastructure.projections.parquet.policy import (
    ParquetProjectionPolicy,
    policy_from_profile,
)
from infrastructure.projections.parquet.store import (
    ParquetProjectionStore,
    parquet_candidate_name,
)
from infrastructure.projections.parquet.terms import (
    assertion_id_from_node,
    identifier_from_iri,
    identifier_iri,
    namespace_of,
    term_value,
)
from infrastructure.projections.parquet.writer import parquet_bytes

ASN_NODE_PREFIX = "urn:assertion:"


class ParquetDataSource(Protocol):
    """Provides the authoritative RDF release for a release id."""

    def get(self, release_id: str) -> RDFDataset | None:
        """Return the RDF dataset for ``release_id``, if available."""
        ...


class MemoryParquetDataSource:
    """In-memory ParquetDataSource for tests and demos."""

    def __init__(self) -> None:
        self._datasets: dict[str, RDFDataset] = {}

    def put(self, release_id: str, dataset: RDFDataset) -> None:
        """Register an RDF dataset for ``release_id``."""
        self._datasets[release_id] = dataset

    def get(self, release_id: str) -> RDFDataset | None:
        return self._datasets.get(release_id)


class ParquetProjection(BaseModel):
    """The full derived analytical content, in canonical plain rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    datasets: dict[str, tuple[dict[str, object], ...]] = Field(default_factory=dict)
    columns: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @property
    def row_count(self) -> int:
        """Total number of rows across all datasets."""
        return sum(len(rows) for rows in self.datasets.values())

    @property
    def dataset_names(self) -> tuple[str, ...]:
        """Names of all datasets, in deterministic order."""
        return tuple(sorted(self.datasets))


class ExpectedParquet(BaseModel):
    """The full expected projection content, derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: ParquetProjection

    @property
    def assertion_count(self) -> int:
        """Number of assertion rows in the expected projection."""
        return len(self.projection.datasets.get("assertions", ()))

    @property
    def entity_count(self) -> int:
        """Number of entity rows in the expected projection."""
        return len(self.projection.datasets.get("entities", ()))

    @property
    def relation_count(self) -> int:
        """Number of relation rows in the expected projection."""
        return len(self.projection.datasets.get("relations", ()))

    @property
    def provenance_count(self) -> int:
        """Number of provenance rows in the expected projection."""
        return len(self.projection.datasets.get("provenance", ()))

    @property
    def evidence_count(self) -> int:
        """Number of evidence rows in the expected projection."""
        return len(self.projection.datasets.get("evidence", ()))


class ParquetProjectionBuilder:
    """Materializes analytical datasets from an authoritative RDF release."""

    def __init__(
        self,
        *,
        store: ParquetProjectionStore,
        data_source: ParquetDataSource,
    ) -> None:
        self._store = store
        self._data_source = data_source

    def derive(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ParquetProjection:
        """Derive the analytical projection from the RDF release."""
        dataset = self._data_source.get(release_id)
        if dataset is None:
            raise MissingParquetReleaseError(release_id)
        policy = policy_from_profile(profile)

        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        provenance = dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))

        approved_rows = self._graph_rows(approved, policy=policy)
        source_rows = self._graph_rows(source, policy=None)
        assertion_rows = self._assertion_rows(approved_rows, source_rows)

        datasets: dict[str, tuple[dict[str, object], ...]] = {}
        if policy.dataset_included("entities"):
            datasets["entities"] = self._entities(assertion_rows)
        if policy.dataset_included("relations"):
            datasets["relations"] = self._relations(assertion_rows)
        if policy.dataset_included("assertions"):
            datasets["assertions"] = assertion_rows
        if policy.dataset_included("provenance"):
            datasets["provenance"] = self._provenance(provenance, assertion_rows, policy)
        if policy.dataset_included("evidence"):
            datasets["evidence"] = self._evidence(provenance, assertion_rows, policy)

        columns = {
            "entities": DATASET_COLUMNS["entities"],
            "relations": DATASET_COLUMNS["relations"],
            "assertions": DATASET_COLUMNS["assertions"],
            "provenance": ("assertion_id",) + policy.provenance_columns,
            "evidence": ("evidence_id", "claim_id") + policy.evidence_columns,
        }
        return ParquetProjection(
            datasets=datasets,
            columns={name: columns[name] for name in datasets},
        )

    def expected(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ExpectedParquet:
        """Derive the expected projection with backend-neutral summaries."""
        return ExpectedParquet(projection=self.derive(release_id, profile))

    def build(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> int:
        """Build the analytical projection under the candidate store key.

        Returns the total number of rows materialized. The candidate is
        always written under its own distinct store key and never touches
        the active projection.
        """
        store_key = parquet_candidate_name(projection_id)
        if self._store.has_projection(store_key):
            raise ParquetProjectionError(
                f"candidate already exists for projection: {projection_id}"
            )
        projection = self.derive(release_id, profile)
        for name in projection.dataset_names:
            data = parquet_bytes(projection.datasets[name], projection.columns[name])
            self._store.write_dataset(store_key, name, data)
        return projection.row_count

    def _graph_rows(
        self,
        graph: NamedGraph | None,
        *,
        policy: ParquetProjectionPolicy | None,
    ) -> tuple[dict[str, object], ...]:
        if graph is None:
            return ()
        rows: list[dict[str, object]] = []
        for _subject_key, triples in sorted(self._group(graph).items()):
            row = self._row(term_value(triples[0].subject), triples, policy)
            if row is not None:
                rows.append(row)
        rows.sort(key=lambda row: str(row["assertion_id"]))
        return tuple(rows)

    def _row(
        self,
        node_value: str,
        triples: list[Triple],
        policy: ParquetProjectionPolicy | None,
    ) -> dict[str, object] | None:
        by_predicate: dict[str, list[Triple]] = {}
        for triple in triples:
            by_predicate.setdefault(triple.predicate.value, []).append(triple)

        predicate = self._first(by_predicate.get(ASN_PREDICATE))
        subject_id = self._identifier_value(by_predicate.get(ASN_SUBJECT))
        if predicate is None or subject_id is None:
            return None
        assertion_type = self._first(by_predicate.get(RDF_TYPE)) or ""
        object_id = self._identifier_value(by_predicate.get(ASN_OBJECT))
        value = self._first(by_predicate.get(ASN_VALUE))
        state = self._first(by_predicate.get(ASN_STATE))

        if policy is not None:
            if not self._included(predicate, assertion_type, subject_id, object_id, policy):
                return None
            predicate = policy.transformed_map.get(predicate, predicate)

        kind = "relationship" if assertion_type == ASN_TYPE_RELATIONSHIP else "attribute"
        return {
            "assertion_id": assertion_id_from_node(node_value),
            "kind": kind,
            "subject": subject_id,
            "predicate": predicate,
            "object": object_id,
            "value": value,
            "state": state,
        }

    @staticmethod
    def _included(
        predicate: str,
        assertion_type: str,
        subject_id: str,
        object_id: str | None,
        policy: ParquetProjectionPolicy,
    ) -> bool:
        if policy.included_relations and predicate not in policy.included_relations:
            return False
        if predicate in policy.dropped_predicates:
            return False
        if predicate in policy.unsupported_semantics:
            if policy.unsupported_behavior is UnsupportedBehavior.ERROR:
                raise ParquetUnsupportedSemanticsError(predicate, policy.profile_id)
            if policy.unsupported_behavior is UnsupportedBehavior.SKIP:
                return False
        if (
            policy.included_assertion_types
            and assertion_type not in policy.included_assertion_types
        ):
            return False
        if (
            policy.included_entity_types
            and namespace_of(subject_id) not in policy.included_entity_types
        ):
            return False
        if (
            object_id is not None
            and policy.included_entity_types
            and namespace_of(object_id) not in policy.included_entity_types
        ):
            return False
        return True

    @staticmethod
    def _assertion_rows(
        approved: tuple[dict[str, object], ...],
        source: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        rows = [dict(row) for row in approved] + [dict(row) for row in source]
        rows.sort(key=lambda row: str(row["assertion_id"]))
        return tuple(rows)

    @staticmethod
    def _entities(
        assertion_rows: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        entries: dict[str, str] = {}
        for row in assertion_rows:
            subject = str(row["subject"])
            entries.setdefault(subject, namespace_of(subject))
            object_id = row.get("object")
            if object_id is not None:
                object_value = str(object_id)
                entries.setdefault(object_value, namespace_of(object_value))
        return tuple(
            {"entity_id": entity_id, "namespace": namespace}
            for entity_id, namespace in sorted(entries.items())
        )

    @staticmethod
    def _relations(
        assertion_rows: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        rows = [
            {
                "assertion_id": row["assertion_id"],
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": row["object"],
                "state": row["state"],
            }
            for row in assertion_rows
            if row.get("kind") == "relationship"
        ]
        rows.sort(key=lambda row: str(row["assertion_id"]))
        return tuple(rows)

    @classmethod
    def _provenance(
        cls,
        graph: NamedGraph | None,
        assertion_rows: tuple[dict[str, object], ...],
        policy: ParquetProjectionPolicy,
    ) -> tuple[dict[str, object], ...]:
        by_node = cls._by_node(graph)
        rows: list[dict[str, object]] = []
        for assertion in sorted(assertion_rows, key=lambda row: str(row["assertion_id"])):
            node = f"{ASN_NODE_PREFIX}{assertion['assertion_id']}"
            predicates = by_node.get(node)
            if predicates is None:
                continue
            row: dict[str, object] = {"assertion_id": assertion["assertion_id"]}
            for column in policy.provenance_columns:
                row[column] = cls._provenance_value(column, predicates)
            rows.append(row)
        rows.sort(key=lambda row: str(row["assertion_id"]))
        return tuple(rows)

    @staticmethod
    def _provenance_value(
        column: str,
        predicates: dict[str, list[str]],
    ) -> object:
        if column == "agent":
            return identifier_from_iri(
                ParquetProjectionBuilder._first_value(predicates.get(PROV_AGENT))
            )
        if column == "activity":
            return identifier_from_iri(
                ParquetProjectionBuilder._first_value(predicates.get(PROV_ACTIVITY))
            )
        if column == "asserted_at":
            return utc_naive_iso(
                ParquetProjectionBuilder._first_value(predicates.get(PROV_ASSERTED_AT))
            )
        if column == "method":
            return ParquetProjectionBuilder._first_value(predicates.get(PROV_METHOD))
        if column == "input_assertions":
            return ParquetProjectionBuilder._identifier_list(predicates.get(PROV_INPUT_ASSERTION))
        if column == "input_resources":
            return ParquetProjectionBuilder._identifier_list(predicates.get(PROV_INPUT_RESOURCE))
        return None

    @classmethod
    def _evidence(
        cls,
        graph: NamedGraph | None,
        assertion_rows: tuple[dict[str, object], ...],
        policy: ParquetProjectionPolicy,
    ) -> tuple[dict[str, object], ...]:
        by_node = cls._by_node(graph)
        rows: list[dict[str, object]] = []
        for assertion in sorted(assertion_rows, key=lambda row: str(row["assertion_id"])):
            node = f"{ASN_NODE_PREFIX}{assertion['assertion_id']}"
            evidence_iris = sorted(by_node.get(node, {}).get(EV_EVIDENCE, []))
            for evidence_iri in evidence_iris:
                evidence_id = identifier_from_iri(evidence_iri)
                if evidence_id is None:
                    continue
                predicates = by_node.get(identifier_iri(evidence_id), {})
                row: dict[str, object] = {
                    "evidence_id": evidence_id,
                    "claim_id": str(assertion["assertion_id"]),
                }
                for column in policy.evidence_columns:
                    row[column] = cls._evidence_value(column, predicates)
                rows.append(row)
        rows.sort(key=lambda row: (str(row["evidence_id"]), str(row["claim_id"])))
        return tuple(rows)

    @staticmethod
    def _evidence_value(
        column: str,
        predicates: dict[str, list[str]],
    ) -> object:
        if column == "kind":
            return ParquetProjectionBuilder._first_value(predicates.get(EV_KIND))
        if column == "record_id":
            return identifier_from_iri(
                ParquetProjectionBuilder._first_value(predicates.get(EV_RECORD))
            )
        if column == "artifact_id":
            return identifier_from_iri(
                ParquetProjectionBuilder._first_value(predicates.get(EV_ARTIFACT))
            )
        if column == "obtained_at":
            return utc_naive_iso(
                ParquetProjectionBuilder._first_value(predicates.get(EV_OBTAINED_AT))
            )
        return None

    @staticmethod
    def _by_node(
        graph: NamedGraph | None,
    ) -> dict[str, dict[str, list[str]]]:
        grouped: dict[str, dict[str, list[str]]] = {}
        if graph is None:
            return grouped
        for triple in graph.triples:
            node = term_value(triple.subject)
            grouped.setdefault(node, {}).setdefault(triple.predicate.value, []).append(
                term_value(triple.object)
            )
        return grouped

    @staticmethod
    def _identifier_list(values: list[str] | None) -> list[str]:
        if values is None:
            return []
        return sorted(
            identifier for identifier in map(identifier_from_iri, values) if identifier is not None
        )

    @staticmethod
    def _first(triples: list[Triple] | None) -> str | None:
        if not triples:
            return None
        return term_value(triples[0].object)

    @staticmethod
    def _first_value(values: list[str] | None) -> str | None:
        if not values:
            return None
        return values[0]

    @staticmethod
    def _identifier_value(triples: list[Triple] | None) -> str | None:
        value = ParquetProjectionBuilder._first(triples)
        return identifier_from_iri(value)

    @staticmethod
    def _group(graph: NamedGraph) -> dict[str, list[Triple]]:
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            by_subject.setdefault(term_value(triple.subject), []).append(triple)
        return by_subject
