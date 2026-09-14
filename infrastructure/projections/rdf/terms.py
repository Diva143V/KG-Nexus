"""Canonical RDF terms: deterministic string forms and identifier helpers.

RDF is the projection's own format, so this backend never translates into a
different data model. These helpers provide the deterministic string forms
used for sorting, comparing, and reconciling projected RDF content.
"""

from __future__ import annotations

from core.rdf.terms import IRI, BlankNode, RDFLiteral, Triple

IDENTIFIER_PREFIX = "urn:identifier:"


def term_value(term: IRI | BlankNode | RDFLiteral) -> str:
    """The plain string value of an RDF term."""
    if isinstance(term, RDFLiteral):
        return term.value
    if isinstance(term, IRI):
        return term.value
    return f"_:{term.label}"


def term_key(term: IRI | BlankNode | RDFLiteral) -> str:
    """Deterministic, collision-free key for an RDF term."""
    if isinstance(term, IRI):
        return f"i:{term.value}"
    if isinstance(term, RDFLiteral):
        if term.datatype is not None:
            return f"l:{term.datatype}:{term.value}"
        return f"l:@{term.language}:{term.value}"
    return f"b:{term.label}"


def triple_key(triple: Triple) -> tuple[str, str, str]:
    """Deterministic sort key for a triple."""
    return term_key(triple.subject), term_key(triple.predicate), term_key(triple.object)


def canonical_triple(graph_name: str, triple: Triple) -> str:
    """Deterministic string form of a triple scoped by its graph."""
    return (
        f"{graph_name}|{term_key(triple.subject)}|"
        f"{term_key(triple.predicate)}|{term_key(triple.object)}"
    )


def namespace_of(identifier: str) -> str:
    """Namespace of a canonical identifier (its type hint)."""
    return identifier.split(":", 1)[0] if ":" in identifier else identifier


def identifier_iri(identifier: str) -> str:
    """RDF IRI form of a canonical identifier string."""
    return f"{IDENTIFIER_PREFIX}{identifier}"


def identifier_from_iri(value: str) -> str:
    """Canonical identifier from its RDF IRI form."""
    return value.removeprefix(IDENTIFIER_PREFIX)
