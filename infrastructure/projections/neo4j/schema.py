"""RDF -> Neo4j data model.

Neo4j is a derived projection: RDF remains authoritative. Every
Neo4j-specific mapping decision lives in this module (and its siblings in
this backend) — Core never learns about them.

Mapping (documented):

RDF -> NODE
    Every entity referenced by an assertion (ASN_SUBJECT or ASN_OBJECT)
    becomes an ``Entity`` node. The node ``id`` is the canonical identifier
    (e.g. ``gene:EGFR``). The RDF IRI form ``urn:identifier:<id>``
    round-trips through ``identifier_iri``.

RDF -> RELATIONSHIP
    Every relationship assertion (an assertion node with ASN_OBJECT) becomes
    a Neo4j relationship. Its ``type`` is a readable form of the predicate,
    and its direction is ASN_SUBJECT -> ASN_OBJECT. The assertion itself is
    preserved verbatim on the relationship as properties (predicate, state,
    provenance, both identifier IRIs).

RDF -> PROPERTY
    Every attribute assertion (an assertion node with ASN_VALUE) becomes a
    property on the subject ``Entity`` node, using the ``attr_*`` scheme
    below so the assertion can be reconstructed losslessly.

IDENTIFIER
    Canonical form ``<namespace>:<value>``; RDF IRI form
    ``urn:identifier:<namespace>:<value>``. The namespace doubles as the
    entity type for projection filtering.

PROVENANCE
    Provenance triples (PROV_AGENT / PROV_ACTIVITY / PROV_ASSERTED_AT /
    PROV_METHOD) are copied onto the corresponding relationship or
    attribute property, so provenance remains reachable from the projection.

ASSERTION
    No assertion is ever dropped. Relationship assertions and attribute
    assertions are both preserved with their predicate, state, and
    provenance so reconciliation can verify nothing was lost.
"""

from __future__ import annotations

import re
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

ENTITY_LABEL = "Entity"

IDENTIFIER_PREFIX = "urn:identifier:"
ASSERTION_PREFIX = "urn:assertion:"
PREDICATE_PREFIX = "urn:predicate:"

PROP_ID = "id"
PROP_NAMESPACE = "namespace"
PROP_ASSERTION_IRI = "assertion_iri"
PROP_PREDICATE = "predicate"
PROP_STATE = "state"
PROP_SUBJECT_IRI = "subject_iri"
PROP_OBJECT_IRI = "object_iri"
PROP_AGENT_ID = "agent_id"
PROP_ACTIVITY_ID = "activity_id"
PROP_ASSERTED_AT = "asserted_at"
PROP_METHOD = "method"

ATTR_VALUE = "attr_value"
ATTR_STATE = "attr_state"
ATTR_ASSERTION = "attr_assertion"
ATTR_PREDICATE = "attr_predicate"
ATTR_AGENT = "attr_agent"
ATTR_ACTIVITY = "attr_activity"
ATTR_ASSERTED = "attr_asserted"
ATTR_METHOD = "attr_method"


class Neo4jNode(BaseModel):
    """A node in the Neo4j-like store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    labels: tuple[str, ...] = Field(default_factory=tuple)
    properties: dict[str, str] = Field(default_factory=dict)


class Neo4jRelationship(BaseModel):
    """A typed, directed relationship in the Neo4j-like store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    start_node_id: str = Field(min_length=1)
    end_node_id: str = Field(min_length=1)
    properties: dict[str, str] = Field(default_factory=dict)


def identifier_iri(identifier: str) -> str:
    """RDF IRI form of a canonical identifier, e.g. ``gene:EGFR``."""
    return f"{IDENTIFIER_PREFIX}{identifier}"


def identifier_from_iri(value: str) -> str:
    """Canonical identifier from its RDF IRI form."""
    return value.removeprefix(IDENTIFIER_PREFIX)


def assertion_iri(assertion_id: str) -> str:
    """RDF IRI form of an assertion id."""
    return f"{ASSERTION_PREFIX}{assertion_id}"


def assertion_id_from_iri(value: str) -> str:
    """Assertion id from its RDF assertion-node IRI."""
    return value.removeprefix(ASSERTION_PREFIX)


def namespace_of(identifier: str) -> str:
    """Namespace of a canonical identifier (its type hint)."""
    return identifier.split(":", 1)[0] if ":" in identifier else identifier


def predicate_type(predicate: str) -> str:
    """Readable relationship type for a predicate.

    ``urn:predicate:interacts_with`` becomes ``interacts_with``; a
    predicate without the standard prefix is used unchanged.
    """
    if predicate.startswith(PREDICATE_PREFIX):
        return predicate.removeprefix(PREDICATE_PREFIX)
    return predicate


def neo4j_candidate_name(projection_id: str) -> str:
    """Neo4j store key for a projection's candidate.

    Candidates are always built under a distinct name and never into the
    active projection.
    """
    return f"neo4j_{projection_id}_candidate"


def digest(value: str) -> str:
    """Stable sha256 hex digest, matching Core's canonical record digest."""
    return sha256(value.encode("utf-8")).hexdigest()


def entity_node(identifier: str) -> Neo4jNode:
    """Neo4j node for an entity identifier (RDF -> NODE mapping)."""
    return Neo4jNode(
        id=identifier,
        labels=(ENTITY_LABEL,),
        properties={
            PROP_ID: identifier,
            PROP_NAMESPACE: namespace_of(identifier),
        },
    )


def relationship_for(
    *,
    assertion_id: str,
    predicate: str,
    subject: str,
    object: str,
    state: str,
    agent_id: str | None = None,
    activity_id: str | None = None,
    asserted_at: str | None = None,
    method: str | None = None,
) -> Neo4jRelationship:
    """Neo4j relationship for a relationship assertion (RDF -> RELATIONSHIP)."""
    properties: dict[str, str] = {
        PROP_ASSERTION_IRI: assertion_iri(assertion_id),
        PROP_PREDICATE: predicate,
        PROP_STATE: state,
        PROP_SUBJECT_IRI: identifier_iri(subject),
        PROP_OBJECT_IRI: identifier_iri(object),
    }
    if agent_id is not None:
        properties[PROP_AGENT_ID] = agent_id
    if activity_id is not None:
        properties[PROP_ACTIVITY_ID] = activity_id
    if asserted_at is not None:
        properties[PROP_ASSERTED_AT] = asserted_at
    if method is not None:
        properties[PROP_METHOD] = method
    return Neo4jRelationship(
        id=assertion_id,
        type=predicate_type(predicate),
        start_node_id=subject,
        end_node_id=object,
        properties=properties,
    )


def attribute_properties(
    *,
    assertion_id: str,
    predicate: str,
    value: str,
    state: str,
    agent_id: str | None = None,
    activity_id: str | None = None,
    asserted_at: str | None = None,
    method: str | None = None,
) -> dict[str, str]:
    """Node properties carrying an attribute assertion (RDF -> PROPERTY).

    The scheme is ``attr_value_<safe_key>`` (the canonical value),
    ``attr_predicate_<safe_key>`` (the original predicate), and
    ``attr_assertion_<safe_key>`` (the assertion IRI) plus optional
    provenance properties. It is lossless: the assertion can be fully
    reconstructed from these properties.
    """
    key = safe_key(predicate)
    properties = {
        f"{ATTR_VALUE}_{key}": value,
        f"{ATTR_STATE}_{key}": state,
        f"{ATTR_PREDICATE}_{key}": predicate,
        f"{ATTR_ASSERTION}_{key}": assertion_iri(assertion_id),
    }
    if agent_id is not None:
        properties[f"{ATTR_AGENT}_{key}"] = agent_id
    if activity_id is not None:
        properties[f"{ATTR_ACTIVITY}_{key}"] = activity_id
    if asserted_at is not None:
        properties[f"{ATTR_ASSERTED}_{key}"] = asserted_at
    if method is not None:
        properties[f"{ATTR_METHOD}_{key}"] = method
    return properties


def safe_key(predicate: str) -> str:
    """Deterministic, collision-free property suffix for a predicate."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", predicate)
