"""Canonical term helpers for the search projection.

These helpers provide the deterministic string forms of RDF terms and
identifiers used while building the search documents. They mirror the
identifier IRI conventions of the authoritative RDF writer.
"""

from __future__ import annotations

from core.rdf.terms import IRI, BlankNode, RDFLiteral

IDENTIFIER_PREFIX = "urn:identifier:"
ASSERTION_PREFIX = "urn:assertion:"


def term_value(term: IRI | BlankNode | RDFLiteral) -> str:
    """The plain string value of an RDF term."""
    if isinstance(term, RDFLiteral):
        return term.value
    if isinstance(term, IRI):
        return term.value
    return f"_:{term.label}"


def namespace_of(identifier: str) -> str:
    """Namespace of a canonical identifier (its type hint)."""
    return identifier.split(":", 1)[0] if ":" in identifier else identifier


def identifier_iri(identifier: str) -> str:
    """RDF IRI form of a canonical identifier string."""
    return f"{IDENTIFIER_PREFIX}{identifier}"


def identifier_from_iri(value: str | None) -> str | None:
    """Canonical identifier from its RDF IRI form."""
    if value is None:
        return None
    return value.removeprefix(IDENTIFIER_PREFIX)


def assertion_id_from_node(node_value: str) -> str:
    """Canonical assertion id from an assertion node value."""
    return node_value.removeprefix(ASSERTION_PREFIX)
