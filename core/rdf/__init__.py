"""Authoritative RDF semantic layer.

RDF is authoritative: the RDF dataset is the single source of truth for
the knowledge graph. ``RDFAuthority`` is the only entry point Core uses;
concrete backends live under ``infrastructure/rdf``.
"""

from __future__ import annotations

from core.rdf.authority import RDFAuthority
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.reader import RDFReleaseReader, ReleaseSnapshot
from core.rdf.terms import IRI, RDFLiteral, Triple
from core.rdf.writer import RDFReleaseWriter

__all__ = [
    "IRI",
    "NamedGraph",
    "NamedGraphCategory",
    "RDFAuthority",
    "RDFDataset",
    "RDFLiteral",
    "RDFReleaseReader",
    "RDFReleaseWriter",
    "ReleaseSnapshot",
    "Triple",
    "graph_name",
]
