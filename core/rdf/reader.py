"""RDFReleaseReader: read an authoritative RDF snapshot back into a model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.rdf.graph import NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import IRI, RDFLiteral
from core.rdf.writer import (
    ASN_STATE,
    RLS_CREATED_AT,
    RLS_DIGEST,
    RLS_PUBLISHED_AT,
    RLS_STATUS,
    RLS_VERSION,
)


class ReleaseSnapshot(BaseModel):
    """Summary read from a release's RDF snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release_id: str
    version: str
    status: str
    created_at: str | None = None
    published_at: str | None = None
    digest: str | None = None
    source_assertion_count: int = 0
    approved_assertion_count: int = 0


class RDFReleaseReader:
    """Extracts a summary view from an authoritative RDF snapshot."""

    def read(self, dataset: RDFDataset) -> ReleaseSnapshot:
        """Read release metadata and assertion counts from a snapshot."""
        metadata = dataset.graph(graph_name(NamedGraphCategory.RELEASE_METADATA))
        if metadata is None:
            raise ValueError("snapshot has no release metadata graph")

        fields: dict[str, object] = {
            "source_assertion_count": self._count_states(
                dataset, NamedGraphCategory.SOURCE_ASSERTION
            ),
            "approved_assertion_count": self._count_states(
                dataset, NamedGraphCategory.APPROVED_ASSERTION
            ),
        }
        for triple in metadata.triples:
            subject = self._term_to_str(triple.subject)
            fields.setdefault("release_id", subject)
            value = self._object_value(triple.object)
            predicate = triple.predicate.value
            if predicate == RLS_VERSION:
                fields["version"] = value
            elif predicate == RLS_STATUS:
                fields["status"] = value
            elif predicate == RLS_CREATED_AT:
                fields["created_at"] = value
            elif predicate == RLS_PUBLISHED_AT:
                fields["published_at"] = value
            elif predicate == RLS_DIGEST:
                fields["digest"] = value

        missing = {"version", "status"} - fields.keys()
        if missing:
            raise ValueError(f"release metadata is missing: {sorted(missing)}")
        return ReleaseSnapshot(**fields)

    @staticmethod
    def _count_states(dataset: RDFDataset, category: NamedGraphCategory) -> int:
        graph = dataset.graph(graph_name(category))
        if graph is None:
            return 0
        return sum(
            1
            for triple in graph.triples
            if isinstance(triple.predicate, IRI) and triple.predicate.value == ASN_STATE
        )

    @staticmethod
    def _term_to_str(term: IRI | RDFLiteral | object) -> str:
        if isinstance(term, IRI):
            return term.value
        if isinstance(term, RDFLiteral):
            return term.value
        return str(term)

    @staticmethod
    def _object_value(term: IRI | RDFLiteral | object) -> str:
        if isinstance(term, RDFLiteral):
            return term.value
        if isinstance(term, IRI):
            return term.value
        return str(term)
