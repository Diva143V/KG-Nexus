"""Backend-independent projection reconciliation.

A projection is always reconciled against the authoritative RDF release it
was derived from. Reconciliation is expressed with backend-neutral concepts:

* assertion count / entity count / relation count;
* assertion digest;
* missing, unexpected, and transformed records.

Core computes the authoritative reference directly from the RDF dataset and
compares it against whatever a backend reports, so the comparison never
depends on backend-specific storage or schemas.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile, ReconciliationStrategy
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import IRI, BlankNode, RDFLiteral, Triple

APPROVED_GRAPH = "urn:graph:approved_assertion"

ASN_SUBJECT = "urn:assertion:subject"
ASN_PREDICATE = "urn:assertion:predicate"
ASN_OBJECT = "urn:assertion:object"
ASN_VALUE = "urn:assertion:value"
ASN_STATE = "urn:assertion:state"

RELATIONSHIP = "relationship"
ATTRIBUTE = "attribute"


class ProjectedRecord(BaseModel):
    """One projection record in backend-neutral terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    digest: str = Field(min_length=1)


class ReconciliationReport(BaseModel):
    """The outcome of reconciling one projection against its RDF source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    assertion_digest: str = Field(min_length=1)
    missing_records: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_records: tuple[str, ...] = Field(default_factory=tuple)
    transformed_records: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def reconciled(self) -> bool:
        """True when the projection matches the authoritative RDF source."""
        return not (self.missing_records or self.unexpected_records or self.transformed_records)


class ReconciliationResult(BaseModel):
    """Backend-independent result of a reconciliation pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    strategy: ReconciliationStrategy
    report: ReconciliationReport

    @property
    def reconciled(self) -> bool:
        """Whether the projection matches its authoritative RDF release."""
        return self.report.reconciled


class ProjectionReconciler:
    """Compares projection records against the authoritative RDF release.

    The reconciler is deterministic: the authoritative reference records are
    derived from the RDF dataset and sorted, so the same release always
    produces the same comparison.
    """

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
        dataset: RDFDataset,
        projected_records: tuple[ProjectedRecord, ...],
    ) -> ReconciliationResult:
        """Reconcile backend-reported records against the RDF release."""
        authoritative = self.authoritative_records(dataset)
        report = self.compare(
            strategy=profile.reconciliation_strategy,
            authoritative_records=authoritative,
            projected_records=projected_records,
        )
        return ReconciliationResult(
            projection_id=projection_id,
            release_id=release_id,
            strategy=profile.reconciliation_strategy,
            report=report,
        )

    def authoritative_records(self, dataset: RDFDataset) -> tuple[ProjectedRecord, ...]:
        """Derive the authoritative reference records from the RDF release."""
        graph = dataset.graph(APPROVED_GRAPH)
        if graph is None:
            return ()
        return self._records_from_graph(graph)

    def compare(
        self,
        *,
        strategy: ReconciliationStrategy,
        authoritative_records: tuple[ProjectedRecord, ...],
        projected_records: tuple[ProjectedRecord, ...],
    ) -> ReconciliationReport:
        """Compare authoritative RDF records against backend-reported records."""
        authoritative_by_key = {(r.kind, r.key): r for r in authoritative_records}
        projected_by_key = {(r.kind, r.key): r for r in projected_records}

        missing = sorted(
            {
                f"{kind}:{key}"
                for (kind, key) in authoritative_by_key.keys() - projected_by_key.keys()
            }
        )
        unexpected = sorted(
            {
                f"{kind}:{key}"
                for (kind, key) in projected_by_key.keys() - authoritative_by_key.keys()
            }
        )
        transformed = sorted(
            f"{kind}:{key}"
            for (kind, key) in authoritative_by_key.keys() & projected_by_key.keys()
            if authoritative_by_key[(kind, key)].digest != projected_by_key[(kind, key)].digest
        )

        assertion_digest = self._assertion_digest(authoritative_records)
        if strategy is ReconciliationStrategy.STATS:
            missing = unexpected = transformed = []
        if strategy is ReconciliationStrategy.DIGEST:
            projected_digest = self._assertion_digest(projected_records)
            if projected_digest != assertion_digest:
                transformed = ["assertion-digest"]
            else:
                missing = unexpected = transformed = []
        return ReconciliationReport(
            assertion_count=self._count(authoritative_records, "assertion"),
            entity_count=self._count(authoritative_records, "entity"),
            relation_count=self._count(authoritative_records, "relation"),
            assertion_digest=assertion_digest,
            missing_records=tuple(missing),
            unexpected_records=tuple(unexpected),
            transformed_records=tuple(transformed),
        )

    def _records_from_graph(self, graph: NamedGraph) -> tuple[ProjectedRecord, ...]:
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            subject = _term_value(triple.subject)
            by_subject.setdefault(subject, []).append(triple)

        records: list[ProjectedRecord] = []
        for subject, triples in sorted(by_subject.items()):
            for triple in sorted(triples, key=_triple_key):
                predicate = triple.predicate.value
                if predicate == ASN_SUBJECT:
                    records.append(
                        ProjectedRecord(
                            kind="entity",
                            key=_term_value(triple.object),
                            digest=self._digest(_term_value(triple.object)),
                        )
                    )
                elif predicate == ASN_OBJECT:
                    records.append(
                        ProjectedRecord(
                            kind="relation",
                            key=f"{subject}:{ASN_OBJECT}:{_term_value(triple.object)}",
                            digest=self._digest(f"{subject}:{_term_value(triple.object)}"),
                        )
                    )
                elif predicate == ASN_PREDICATE:
                    records.append(
                        ProjectedRecord(
                            kind="assertion",
                            key=subject,
                            digest=self._digest(_term_value(triple.object)),
                        )
                    )
        return tuple(sorted(records, key=lambda record: (record.kind, record.key)))

    @staticmethod
    def _assertion_digest(records: tuple[ProjectedRecord, ...]) -> str:
        assertions = sorted(record.digest for record in records if record.kind == "assertion")
        serialized = json.dumps(
            assertions,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _count(records: tuple[ProjectedRecord, ...], kind: str) -> int:
        return sum(1 for record in records if record.kind == kind)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _term_value(term: IRI | BlankNode | RDFLiteral) -> str:
    if isinstance(term, RDFLiteral):
        return term.value
    if isinstance(term, IRI):
        return term.value
    return f"_:{term.label}"


def _triple_key(triple: Triple) -> tuple[str, str]:
    return triple.predicate.value, _term_value(triple.object)
