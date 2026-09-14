"""N-Quads serialization for RDF datasets.

Deterministic, plain-text serialization used for export and inspection.
Graphs are emitted in dataset order; triples within a graph are sorted.
"""

from __future__ import annotations

from core.rdf.graph import RDFDataset
from core.rdf.terms import IRI, BlankNode, RDFLiteral, Triple


def to_nquads(dataset: RDFDataset) -> str:
    """Serialize a dataset to N-Quads, one statement per line."""
    lines: list[str] = []
    for graph in dataset.graphs:
        for triple in sorted(graph.triples, key=_quad_key):
            lines.append(
                f"{_nq(triple.subject)} {_nq(triple.predicate)} {_nq(triple.object)}"
                f" <{graph.name}> ."
            )
    return "\n".join(lines)


def _quad_key(triple: Triple) -> tuple[str, str, str]:
    return _nq(triple.subject), _nq(triple.predicate), _nq(triple.object)


def _nq(term: IRI | RDFLiteral | BlankNode) -> str:
    if isinstance(term, IRI):
        return f"<{term.value}>"
    if isinstance(term, RDFLiteral):
        escaped = term.value.replace("\\", "\\\\").replace('"', '\\"')
        if term.datatype is not None:
            return f'"{escaped}"^^<{term.datatype}>'
        return f'"{escaped}"@{term.language}'
    return f"_:{term.label}"
