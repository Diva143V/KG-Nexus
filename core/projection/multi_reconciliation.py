"""Profile-aware, cross-backend projection reconciliation.

RDF is authoritative. Every projection is built from a release through its own
``ProjectionProfile``, and that profile is the contract: it declares what the
projection promises about RDF semantics. This module verifies each projection
against its own declared profile — never against "every RDF feature".

Backends legitimately vary in what they preserve: a graph store, a columnar
analytics store, and a full-text search engine each project the same release
differently. That variety is expected and fine, as long as each honors its own
profile. A projection passes only if:

* all required (preserved) semantics are present with their expected digests;
* all declared transformations match the projection's records;
* intentionally unsupported semantics are explicitly accounted for (declared
  and confirmed absent, never silently dropped or silently included).

Every assertion in the approved RDF graph is classified against the profile:

* ``preserved``     — kept unchanged (assertion digest = source predicate);
* ``transformed``   — kept under a declared predicate remap;
* ``excluded``      — intentionally unsupported (dropped predicate, a
                      ``included_*`` filter, or an ``unsupported`` predicate
                      with SKIP/FLATTEN handling);
* ``error``         — the profile declares the predicate unsupported with
                      ERROR behavior, so no conforming projection can exist.

The comparison then reports missing / unexpected / transformed records,
digest mismatches, the preserved / transformed / unsupported semantics, and a
single deterministic ``conforms`` verdict per projection. A multi-projection
report aggregates every projection of a release so the whole set can be
verified at once.

This is a pure Core capability: it needs no backend-specific storage or
schemas and never assumes any particular downstream store.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import (
    ProjectionProfile,
    ReconciliationStrategy,
    UnsupportedBehavior,
)
from core.projection.reconciliation import ProjectedRecord
from core.rdf.graph import RDFDataset
from core.rdf.terms import IRI, BlankNode, RDFLiteral, Triple

APPROVED_GRAPH = "urn:graph:approved_assertion"

ASN_SUBJECT = "urn:assertion:subject"
ASN_PREDICATE = "urn:assertion:predicate"
ASN_OBJECT = "urn:assertion:object"
ASN_VALUE = "urn:assertion:value"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

ASN_OBJECT_PREDICATE = "urn:assertion:object"
IDENTIFIER_PREFIX = "urn:identifier:"


def identifier_iri(identifier: str) -> str:
    """RDF IRI form of a canonical identifier string."""
    return f"{IDENTIFIER_PREFIX}{identifier}"


def namespace_of(identifier: str) -> str:
    """Namespace (type hint) of a canonical identifier string."""
    return identifier.split(":", 1)[0] if ":" in identifier else identifier


class DigestMismatch(BaseModel):
    """A projected record whose digest does not match the profile's expectation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    expected_digest: str = Field(min_length=1)
    actual_digest: str = Field(min_length=1)


class ProjectionReconciliationReport(BaseModel):
    """Profile-aware reconciliation of one projection against its release.

    ``preserved_records`` / ``transformed_records`` are the record keys
    (``kind:key``) the projection correctly preserved or correctly
    transformed. ``unsupported_records`` are the assertions the profile
    excludes, each confirmed absent and accounted for with its reason.
    ``missing_records`` / ``unexpected_records`` / ``digest_mismatches`` are
    the violations: required-but-absent, present-but-not-expected, and
    present-with-a-different-digest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    strategy: ReconciliationStrategy

    assertion_count: int = Field(ge=0)
    required_assertions: int = Field(ge=0)
    transformed_assertions: int = Field(ge=0)
    excluded_assertions: int = Field(ge=0)
    error_assertions: int = Field(ge=0)

    preserved_records: tuple[str, ...] = Field(default_factory=tuple)
    transformed_records: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_records: tuple[str, ...] = Field(default_factory=tuple)
    missing_records: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_records: tuple[str, ...] = Field(default_factory=tuple)
    digest_mismatches: tuple[DigestMismatch, ...] = Field(default_factory=tuple)

    preserved_semantics: tuple[str, ...] = Field(default_factory=tuple)
    transformed_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)

    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def conforms(self) -> bool:
        """Whether the projection honors its declared profile.

        True only when every required semantic is preserved, every declared
        transformation matches, and every unsupported semantic is accounted
        for — no missing, unexpected, or mismatched records, and no profile
        that is unsatisfiable with ERROR behavior.
        """
        return not (
            self.missing_records or self.unexpected_records or self.digest_mismatches or self.errors
        )


class ProjectionInput(BaseModel):
    """One projection to verify, described in backend-neutral terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    profile: ProjectionProfile
    projected_records: tuple[ProjectedRecord, ...] = Field(default_factory=tuple)


class MultiProjectionReconciliationReport(BaseModel):
    """Aggregated, profile-aware reconciliation for one release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release_id: str = Field(min_length=1)
    reports: tuple[ProjectionReconciliationReport, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every projection conforms to its own declared profile."""
        return all(report.conforms for report in self.reports)

    def report_for(self, projection_id: str) -> ProjectionReconciliationReport | None:
        """The per-projection report for ``projection_id``, if present."""
        for report in self.reports:
            if report.projection_id == projection_id:
                return report
        return None


class MultiProjectionReconciler:
    """Verifies each projection against the profile it was built with.

    The reconciler is deterministic: assertions are parsed and classified in
    sorted order, expected records are keyed and compared canonically, and
    every reported tuple is sorted. The same release and profiles always
    produce the same report.
    """

    def reconcile(
        self,
        *,
        release_id: str,
        dataset: RDFDataset,
        projections: Iterable[ProjectionInput],
    ) -> MultiProjectionReconciliationReport:
        """Reconcile every supplied projection against ``release_id``."""
        reports = tuple(
            sorted(
                (
                    self.reconcile_projection(
                        dataset=dataset,
                        projection=projection,
                    )
                    for projection in projections
                ),
                key=lambda report: report.projection_id,
            )
        )
        return MultiProjectionReconciliationReport(
            release_id=release_id,
            reports=reports,
        )

    def reconcile_projection(
        self,
        *,
        dataset: RDFDataset,
        projection: ProjectionInput,
    ) -> ProjectionReconciliationReport:
        """Reconcile one projection against the semantics its profile declares."""
        rows = self._assertions(dataset)
        expected, counts, semantics, unsupported_records, errors = self._expected(
            rows, projection.profile
        )
        projected_by_key = {
            (record.kind, record.key): record.digest for record in projection.projected_records
        }

        missing = sorted(
            f"{kind}:{key}" for (kind, key) in expected if (kind, key) not in projected_by_key
        )
        unexpected = sorted(
            f"{kind}:{key}" for (kind, key) in projected_by_key if (kind, key) not in expected
        )

        preserved_records: list[str] = []
        transformed_records: list[str] = []
        mismatches: list[DigestMismatch] = []
        for (kind, key), (expected_digest, provenance) in sorted(expected.items()):
            actual_digest = projected_by_key.get((kind, key))
            if actual_digest is None:
                continue
            if actual_digest != expected_digest:
                mismatches.append(
                    DigestMismatch(
                        kind=kind,
                        key=key,
                        expected_digest=expected_digest,
                        actual_digest=actual_digest,
                    )
                )
                continue
            if provenance == "transformed":
                transformed_records.append(f"{kind}:{key}")
            else:
                preserved_records.append(f"{kind}:{key}")

        return ProjectionReconciliationReport(
            projection_id=projection.projection_id,
            backend_id=projection.backend_id,
            release_id=projection.release_id,
            profile_id=projection.profile.profile_id,
            strategy=projection.profile.reconciliation_strategy,
            assertion_count=len(rows),
            required_assertions=counts["required"],
            transformed_assertions=counts["transformed"],
            excluded_assertions=counts["excluded"],
            error_assertions=counts["error"],
            preserved_records=tuple(preserved_records),
            transformed_records=tuple(transformed_records),
            unsupported_records=tuple(sorted(unsupported_records)),
            missing_records=tuple(missing),
            unexpected_records=tuple(unexpected),
            digest_mismatches=tuple(mismatches),
            preserved_semantics=tuple(sorted(semantics["preserved"])),
            transformed_semantics=tuple(sorted(semantics["transformed"])),
            unsupported_semantics=tuple(sorted(semantics["unsupported"])),
            errors=tuple(errors),
        )

    def _assertions(self, dataset: RDFDataset) -> tuple[dict[str, object], ...]:
        """Parse the approved graph into per-assertion rows, in sorted order."""
        graph = dataset.graph(APPROVED_GRAPH)
        if graph is None:
            return ()
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            by_subject.setdefault(_term_value(triple.subject), []).append(triple)
        rows: list[dict[str, object]] = []
        for node, triples in sorted(by_subject.items()):
            row = self._row(node, triples)
            if row is not None:
                rows.append(row)
        return tuple(rows)

    @staticmethod
    def _row(node: str, triples: list[Triple]) -> dict[str, object] | None:
        by_predicate: dict[str, list[Triple]] = {}
        for triple in triples:
            by_predicate.setdefault(triple.predicate.value, []).append(triple)
        predicate = _first(by_predicate.get(ASN_PREDICATE))
        subject = _identifier(by_predicate.get(ASN_SUBJECT))
        if predicate is None or subject is None:
            return None
        return {
            "node": node,
            "predicate": predicate,
            "subject": subject,
            "object": _identifier(by_predicate.get(ASN_OBJECT)),
            "value": _first(by_predicate.get(ASN_VALUE)),
            "type": _first(by_predicate.get(RDF_TYPE)) or "",
        }

    @staticmethod
    def _disposition(
        profile: ProjectionProfile,
        predicate: str,
        type_iri: str,
        subject: str,
        object_id: str | None,
    ) -> tuple[str, str | None]:
        """Classify one assertion against the profile: disposition + metadata."""
        if predicate in profile.unsupported_semantics:
            if profile.unsupported_behavior is UnsupportedBehavior.ERROR:
                return "error", None
            if profile.unsupported_behavior is UnsupportedBehavior.SKIP:
                return "excluded", "unsupported"
            return "required", None
        if predicate in profile.dropped_semantics:
            return "excluded", "dropped"
        target = {t.source: t.target for t in profile.transformations}.get(predicate)
        if target is not None:
            return "transformed", target
        if profile.included_assertion_types and type_iri not in profile.included_assertion_types:
            return "excluded", "assertion-type"
        if profile.included_relations and predicate not in profile.included_relations:
            return "excluded", "relation"
        if (
            profile.included_entity_types
            and namespace_of(subject) not in profile.included_entity_types
        ):
            return "excluded", "entity-type"
        if (
            object_id is not None
            and profile.included_entity_types
            and namespace_of(object_id) not in profile.included_entity_types
        ):
            return "excluded", "entity-type"
        return "required", None

    @staticmethod
    def _expected(
        rows: tuple[dict[str, object], ...],
        profile: ProjectionProfile,
    ) -> tuple[
        dict[tuple[str, str], tuple[str, str]],
        dict[str, int],
        dict[str, set[str]],
        set[str],
        list[str],
    ]:
        """Expected records, counts, semantics, unsupported, and errors."""
        expected: dict[tuple[str, str], tuple[str, str]] = {}
        counts = {"required": 0, "transformed": 0, "excluded": 0, "error": 0}
        semantics: dict[str, set[str]] = {
            "preserved": set(),
            "transformed": set(),
            "unsupported": set(),
        }
        unsupported_records: set[str] = set()
        errors: list[str] = []

        for row in rows:
            node = str(row["node"])
            predicate = str(row["predicate"])
            subject = str(row["subject"])
            object_id = row["object"]
            object_id = str(object_id) if object_id is not None else None
            disposition, meta = MultiProjectionReconciler._disposition(
                profile,
                predicate,
                str(row["type"]),
                subject,
                object_id,
            )

            if disposition == "error":
                counts["error"] += 1
                semantics["unsupported"].add(f"{predicate} (error)")
                errors.append(
                    f"profile {profile.profile_id} declares unsupported predicate "
                    f"{predicate} with ERROR behavior"
                )
                continue
            if disposition == "excluded":
                counts["excluded"] += 1
                semantics["unsupported"].add(f"{predicate} ({meta})")
                unsupported_records.add(f"assertion:{node} ({meta})")
                continue
            if disposition == "transformed":
                counts["transformed"] += 1
                semantics["transformed"].add(f"{predicate} -> {meta}")
            else:
                counts["required"] += 1
                semantics["preserved"].add(predicate)

            effective = (meta or predicate) if disposition == "transformed" else predicate
            provenance = "transformed" if disposition == "transformed" else "preserved"
            expected[("assertion", node)] = (
                _digest(effective),
                provenance,
            )
            if object_id is not None:
                object_iri = identifier_iri(object_id)
                relation_key = f"{node}:{ASN_OBJECT_PREDICATE}:{object_iri}"
                expected.setdefault(
                    ("relation", relation_key),
                    (_digest(f"{node}:{object_iri}"), "preserved"),
                )
            subject_iri = identifier_iri(subject)
            expected.setdefault(
                ("entity", subject_iri),
                (_digest(subject_iri), "preserved"),
            )

        return expected, counts, semantics, unsupported_records, errors


def _first(triples: list[Triple] | None) -> str | None:
    if not triples:
        return None
    return _term_value(triples[0].object)


def _identifier(triples: list[Triple] | None) -> str | None:
    value = _first(triples)
    if value is None:
        return None
    return value.removeprefix(IDENTIFIER_PREFIX)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _term_value(term: IRI | BlankNode | RDFLiteral) -> str:
    if isinstance(term, RDFLiteral):
        return term.value
    if isinstance(term, IRI):
        return term.value
    return f"_:{term.label}"
