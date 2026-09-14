"""RDFReleaseWriter: build an authoritative RDF snapshot of a release.

RDF is authoritative. A snapshot captures, per release, the ontology,
mappings, every assertion (split into source and approved graphs by
resolved state), provenance, validation evidence, and release metadata —
including a canonical digest of the assertion records.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.literal import LiteralType, LiteralValue, canonical_literal
from core.assertions.resolver import AssertionStateResolver
from core.assertions.state import AssertionState
from core.digest.digester import CanonicalDigestService
from core.digest.profile import DigestProfile
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import (
    IRI,
    XSD_DATETIME,
    BlankNode,
    RDFLiteral,
    Triple,
    iri,
    string_literal,
)
from core.releases.release import Release

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

PROV_AGENT = "urn:prov:agent"
PROV_ACTIVITY = "urn:prov:activity"
PROV_ASSERTED_AT = "urn:prov:asserted_at"
PROV_METHOD = "urn:prov:method"
PROV_INPUT_ASSERTION = "urn:prov:input_assertion"
PROV_INPUT_RESOURCE = "urn:prov:input_resource"

EV_EVIDENCE = "urn:evidence:evidence"
EV_CLAIM = "urn:evidence:claim"
EV_KIND = "urn:evidence:kind"
EV_RECORD = "urn:evidence:record"
EV_ARTIFACT = "urn:evidence:artifact"
EV_OBTAINED_AT = "urn:evidence:obtained_at"
EV_DETAIL = "urn:evidence:detail"

ASN_SUBJECT = "urn:assertion:subject"
ASN_PREDICATE = "urn:assertion:predicate"
ASN_OBJECT = "urn:assertion:object"
ASN_VALUE = "urn:assertion:value"
ASN_STATE = "urn:assertion:state"
ASN_TYPE = "urn:assertion:type"
ASN_TYPE_RELATIONSHIP = "urn:assertion:RelationshipAssertion"
ASN_TYPE_ATTRIBUTE = "urn:assertion:AttributeAssertion"

RLS_VERSION = "urn:release:version"
RLS_STATUS = "urn:release:status"
RLS_CREATED_AT = "urn:release:created_at"
RLS_PUBLISHED_AT = "urn:release:published_at"
RLS_DIGEST = "urn:release:digest"

_DATATYPES = {
    LiteralType.STRING: "http://www.w3.org/2001/XMLSchema#string",
    LiteralType.INTEGER: "http://www.w3.org/2001/XMLSchema#integer",
    LiteralType.FLOAT: "http://www.w3.org/2001/XMLSchema#double",
    LiteralType.BOOLEAN: "http://www.w3.org/2001/XMLSchema#boolean",
    LiteralType.DATETIME: XSD_DATETIME,
}


def identifier_iri(identifier: str) -> IRI:
    """IRI form of a canonical identifier string."""
    return iri(f"urn:identifier:{identifier}")


def assertion_iri(assertion_id: str) -> IRI:
    """IRI form of an assertion resource."""
    return iri(f"urn:assertion:{assertion_id}")


class RDFReleaseWriter:
    """Builds authoritative RDF snapshots from release content."""

    def __init__(
        self,
        *,
        resolver: AssertionStateResolver | None = None,
        digester: CanonicalDigestService | None = None,
    ) -> None:
        self._resolver = resolver or AssertionStateResolver()
        self._digester = digester or CanonicalDigestService(
            profile=DigestProfile(include_provenance=True)
        )

    def build_snapshot(
        self,
        *,
        release: Release,
        assertions: Sequence[Assertion] = (),
        attribute_assertions: Sequence[AttributeAssertion] = (),
        events: Sequence[AssertionStateEvent] = (),
        ontology: NamedGraph | None = None,
        mapping: NamedGraph | None = None,
        validation: NamedGraph | None = None,
    ) -> RDFDataset:
        """Build the full RDF dataset snapshot for a release."""
        resolved = self._resolved_states(assertions, attribute_assertions, events)

        source_triples: list[Triple] = []
        approved_triples: list[Triple] = []
        provenance_triples: list[Triple] = []
        for assertion in assertions:
            state = resolved[assertion.id.canonical]
            triples = self._relationship_triples(assertion, state)
            target = approved_triples if state is AssertionState.APPROVED else source_triples
            target.extend(triples)
            provenance_triples.extend(self._provenance_triples(assertion))
            provenance_triples.extend(self._evidence_triples(assertion))

        for attribute in attribute_assertions:
            state = resolved[attribute.id.canonical]
            triples = self._attribute_triples(attribute, state)
            target = approved_triples if state is AssertionState.APPROVED else source_triples
            target.extend(triples)
            provenance_triples.extend(self._provenance_triples(attribute))
            provenance_triples.extend(self._evidence_triples(attribute))

        digest = self._digester.digest(
            assertions=assertions,
            attribute_assertions=attribute_assertions,
            events=events,
        )

        graphs = [
            self._graph(NamedGraphCategory.ONTOLOGY, ontology),
            self._graph(NamedGraphCategory.MAPPING, mapping),
            self._sorted_graph(NamedGraphCategory.SOURCE_ASSERTION, source_triples),
            self._sorted_graph(NamedGraphCategory.APPROVED_ASSERTION, approved_triples),
            self._sorted_graph(NamedGraphCategory.PROVENANCE, provenance_triples),
            self._graph(NamedGraphCategory.VALIDATION, validation),
            self._sorted_graph(
                NamedGraphCategory.RELEASE_METADATA,
                self._release_triples(release, digest.digest),
            ),
        ]
        return RDFDataset(graphs=tuple(graphs))

    def _resolved_states(
        self,
        assertions: Sequence[Assertion],
        attribute_assertions: Sequence[AttributeAssertion],
        events: Sequence[AssertionStateEvent],
    ) -> dict[str, AssertionState]:
        by_assertion: dict[str, list[AssertionStateEvent]] = {}
        for event in events:
            by_assertion.setdefault(event.assertion_id.canonical, []).append(event)
        grouped = {key: tuple(value) for key, value in by_assertion.items()}
        resolved: dict[str, AssertionState] = {}
        for assertion in assertions:
            resolved[assertion.id.canonical] = self._resolver.resolve_from(
                assertion.status_at_creation, grouped.get(assertion.id.canonical, ())
            )
        for attribute in attribute_assertions:
            resolved[attribute.id.canonical] = self._resolver.resolve_from(
                attribute.status_at_creation,
                grouped.get(attribute.id.canonical, ()),
            )
        return resolved

    def _relationship_triples(self, assertion: Assertion, state: AssertionState) -> list[Triple]:
        node = assertion_iri(assertion.id.canonical)
        return [
            Triple(
                subject=node,
                predicate=iri(RDF_TYPE),
                object=iri(ASN_TYPE_RELATIONSHIP),
            ),
            _i(node, ASN_SUBJECT, assertion.subject.canonical),
            _s(node, ASN_PREDICATE, assertion.predicate),
            _i(node, ASN_OBJECT, assertion.object.canonical),
            _s(node, ASN_STATE, state.value),
        ]

    def _attribute_triples(
        self, assertion: AttributeAssertion, state: AssertionState
    ) -> list[Triple]:
        node = assertion_iri(assertion.id.canonical)
        return [
            Triple(
                subject=node,
                predicate=iri(RDF_TYPE),
                object=iri(ASN_TYPE_ATTRIBUTE),
            ),
            _i(node, ASN_SUBJECT, assertion.subject.canonical),
            _s(node, ASN_PREDICATE, assertion.predicate),
            Triple(
                subject=node,
                predicate=iri(ASN_VALUE),
                object=self._literal_iri(assertion.value),
            ),
            _s(node, ASN_STATE, state.value),
        ]

    def _literal_iri(self, value: LiteralValue) -> RDFLiteral:
        datatype = _DATATYPES[value.type]
        return RDFLiteral(value=canonical_literal(value), datatype=datatype)

    def _provenance_triples(self, assertion: Assertion | AttributeAssertion) -> list[Triple]:
        node = assertion_iri(assertion.id.canonical)
        provenance = assertion.provenance
        triples: list[Triple] = [
            _i(node, PROV_AGENT, provenance.agent_id.canonical),
            _i(node, PROV_ACTIVITY, provenance.activity_id.canonical),
            Triple(
                subject=node,
                predicate=iri(PROV_ASSERTED_AT),
                object=self._datetime_literal(provenance.asserted_at),
            ),
        ]
        if provenance.method is not None:
            triples.append(_s(node, PROV_METHOD, provenance.method))
        for ref in provenance.input_assertion_refs:
            triples.append(_i(node, PROV_INPUT_ASSERTION, ref.canonical))
        for ref in provenance.input_resource_refs:
            triples.append(_i(node, PROV_INPUT_RESOURCE, ref.canonical))
        return triples

    def _evidence_triples(self, assertion: Assertion | AttributeAssertion) -> list[Triple]:
        node = assertion_iri(assertion.id.canonical)
        triples: list[Triple] = []
        for evidence in sorted(assertion.evidence, key=lambda item: item.id.canonical):
            ev_node = identifier_iri(evidence.id.canonical)
            triples.append(_i(node, EV_EVIDENCE, evidence.id.canonical))
            triples.append(_i(ev_node, EV_CLAIM, assertion.id.canonical))
            triples.append(_s(ev_node, EV_KIND, evidence.kind.value))
            triples.append(_i(ev_node, EV_RECORD, evidence.record_id.canonical))
            if evidence.artifact_id is not None:
                triples.append(_i(ev_node, EV_ARTIFACT, evidence.artifact_id.canonical))
            if evidence.obtained_at is not None:
                triples.append(
                    Triple(
                        subject=ev_node,
                        predicate=iri(EV_OBTAINED_AT),
                        object=self._datetime_literal(evidence.obtained_at),
                    )
                )
            if evidence.detail:
                detail = json.dumps(
                    evidence.detail,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                triples.append(_s(ev_node, EV_DETAIL, detail))
        return triples

    def _release_triples(self, release: Release, digest: str) -> list[Triple]:
        node = identifier_iri(release.id.canonical)
        triples = [
            _s(node, RLS_VERSION, release.version),
            _s(node, RLS_STATUS, release.status.value),
            Triple(
                subject=node,
                predicate=iri(RLS_CREATED_AT),
                object=self._datetime_literal(release.created_at),
            ),
            _s(node, RLS_DIGEST, digest),
        ]
        if release.published_at is not None:
            triples.append(
                Triple(
                    subject=node,
                    predicate=iri(RLS_PUBLISHED_AT),
                    object=self._datetime_literal(release.published_at),
                )
            )
        return triples

    @staticmethod
    def _datetime_literal(value: datetime) -> RDFLiteral:
        if value.tzinfo is None:
            raise ValueError("datetime literal must be timezone-aware")
        return RDFLiteral(value=value.astimezone(UTC).isoformat(), datatype=XSD_DATETIME)

    @staticmethod
    def _graph(category: NamedGraphCategory, graph: NamedGraph | None) -> NamedGraph:
        if graph is None:
            return NamedGraph(name=graph_name(category))
        triples = tuple(sorted(graph.triples, key=_triple_key))
        return NamedGraph(name=graph_name(category), triples=triples)

    @staticmethod
    def _sorted_graph(category: NamedGraphCategory, triples: list[Triple]) -> NamedGraph:
        return NamedGraph(
            name=graph_name(category),
            triples=tuple(sorted(triples, key=_triple_key)),
        )


def _triple_key(triple: Triple) -> tuple[str, str, str]:
    """Deterministic sort key for a triple."""
    return _term_key(triple.subject), _term_key(triple.predicate), _term_key(triple.object)


def _s(subject: IRI | BlankNode, predicate: str, value: str) -> Triple:
    """Build a triple with a string-literal object."""
    return Triple(subject=subject, predicate=iri(predicate), object=string_literal(value))


def _i(subject: IRI | BlankNode, predicate: str, value: str) -> Triple:
    """Build a triple with an identifier-IRI object."""
    return Triple(subject=subject, predicate=iri(predicate), object=identifier_iri(value))


def _term_key(term: IRI | RDFLiteral | BlankNode) -> str:
    if isinstance(term, IRI):
        return f"i:{term.value}"
    if isinstance(term, RDFLiteral):
        if term.datatype is not None:
            return f"l:{term.datatype}:{term.value}"
        return f"l:@{term.language}:{term.value}"
    return f"b:{term.label}"
