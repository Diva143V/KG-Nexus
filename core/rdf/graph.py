"""Named graphs and RDF datasets."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.rdf.terms import Triple


class NamedGraphCategory(StrEnum):
    """Initial named graph categories for release RDF snapshots."""

    ONTOLOGY = "ontology"
    MAPPING = "mapping"
    SOURCE_ASSERTION = "source_assertion"
    APPROVED_ASSERTION = "approved_assertion"
    PROVENANCE = "provenance"
    VALIDATION = "validation"
    RELEASE_METADATA = "release_metadata"


class NamedGraph(BaseModel):
    """A named RDF graph: a set of triples with a graph name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    triples: tuple[Triple, ...] = Field(default_factory=tuple)

    @property
    def size(self) -> int:
        """Number of triples in the graph."""
        return len(self.triples)


class RDFDataset(BaseModel):
    """An immutable collection of named graphs.

    RDF is authoritative: the dataset is the single source of truth for
    the semantic layer. Projections (e.g. Neo4j) are always rebuilt from
    it, never treated as authoritative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    graphs: tuple[NamedGraph, ...] = Field(default_factory=tuple)

    def graph(self, name: str) -> NamedGraph | None:
        """Return the named graph with ``name``, if present."""
        for graph in self.graphs:
            if graph.name == name:
                return graph
        return None

    def graph_names(self) -> tuple[str, ...]:
        """Names of all graphs in the dataset, in order."""
        return tuple(graph.name for graph in self.graphs)

    def triple_count(self) -> int:
        """Total number of triples across all graphs."""
        return sum(graph.size for graph in self.graphs)


def graph_name(category: NamedGraphCategory) -> str:
    """Canonical graph name for a category."""
    return f"urn:graph:{category.value}"
