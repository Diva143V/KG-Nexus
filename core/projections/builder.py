"""ProjectionBuilder: turn authoritative RDF into projection content.

RDF is authoritative. The builder reads an ``RDFDataset`` and produces
``ProjectionContent`` following a ``ProjectionProfile``. Every input
semantic is classified:

* ``preserved_fields`` are carried into node properties unchanged;
* ``transformations`` map a source semantic onto a node, edge, or property;
* ``dropped_semantics`` are recorded as declared, audited omissions;
* ``unsupported_semantics`` follow the profile's declared behavior.

Any semantic the profile does not cover raises ``UndeclaredSemanticsError``:
a projection never silently drops RDF semantics.
"""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.projections.content import ProjectedEdge, ProjectedNode, ProjectionContent
from core.projections.errors import ProjectionError
from core.projections.profile import (
    FieldTransformation,
    ProjectionProfile,
    TransformationKind,
    UnsupportedBehavior,
)
from core.rdf.graph import RDFDataset
from core.rdf.terms import IRI, BlankNode, RDFLiteral


class UndeclaredSemanticsError(ProjectionError):
    """Input RDF semantics not covered by the projection profile."""

    def __init__(self, predicate: str, subject: str) -> None:
        self.predicate = predicate
        self.subject = subject
        super().__init__(
            f"undeclared RDF semantics: predicate {predicate!r} on {subject!r} "
            "is neither preserved, transformed, dropped, nor unsupported "
            "by the profile"
        )


class UnsupportedSemanticsError(ProjectionError):
    """Unsupported RDF semantics when the profile errors on them."""

    def __init__(self, predicate: str, subject: str) -> None:
        self.predicate = predicate
        self.subject = subject
        super().__init__(
            f"unsupported RDF semantics (profile behavior=error): "
            f"predicate {predicate!r} on {subject!r}"
        )


class ProjectionBuilder:
    """Builds projection content from authoritative RDF."""

    def build(
        self,
        *,
        projection_id: Identifier,
        dataset: RDFDataset,
        profile: ProjectionProfile,
    ) -> ProjectionContent:
        """Build deterministic projection content for ``dataset`` per ``profile``."""
        transformations = {t.source: t for t in profile.transformations}
        nodes: dict[str, ProjectedNode] = {}
        edges: list[ProjectedEdge] = []
        dropped: list[str] = []
        unsupported: list[str] = []

        for graph in dataset.graphs:
            for triple in graph.triples:
                subject = _term_key(triple.subject)
                predicate = triple.predicate.value
                if predicate in profile.preserved_fields:
                    self._preserve(nodes, subject, predicate, triple.object)
                    continue
                transformation = transformations.get(predicate)
                if transformation is not None:
                    self._transform(
                        nodes,
                        edges,
                        subject,
                        transformation,
                        triple.object,
                    )
                    continue
                if predicate in profile.dropped_semantics:
                    dropped.append(predicate)
                    continue
                if predicate in profile.unsupported_semantics:
                    self._handle_unsupported(unsupported, predicate, subject, profile)
                    continue
                raise UndeclaredSemanticsError(predicate, subject)

        ordered_nodes = tuple(sorted(nodes.values(), key=lambda node: node.key))
        ordered_edges = tuple(sorted(edges, key=_edge_key))
        return ProjectionContent(
            projection_id=projection_id,
            profile=profile.name,
            profile_version=profile.version,
            nodes=ordered_nodes,
            edges=ordered_edges,
            dropped_semantics=tuple(sorted(set(dropped))),
            unsupported_semantics=tuple(sorted(set(unsupported))),
        )

    @staticmethod
    def _preserve(
        nodes: dict[str, ProjectedNode],
        subject: str,
        predicate: str,
        value: IRI | BlankNode | RDFLiteral,
    ) -> None:
        node = nodes.get(subject)
        if node is None:
            node = ProjectedNode(key=subject, kind="node")
        nodes[subject] = ProjectedNode(
            key=node.key,
            kind=node.kind,
            properties={**node.properties, predicate: _object_value(value)},
        )

    @staticmethod
    def _transform(
        nodes: dict[str, ProjectedNode],
        edges: list[ProjectedEdge],
        subject: str,
        transformation: FieldTransformation,
        value: IRI | BlankNode | RDFLiteral,
    ) -> None:
        if transformation.kind is TransformationKind.PROPERTY:
            ProjectionBuilder._preserve(nodes, subject, transformation.target, value)
            return
        if transformation.kind is TransformationKind.NODE:
            object_value = _object_value(value)
            nodes.setdefault(
                object_value,
                ProjectedNode(key=object_value, kind=transformation.target),
            )
            return
        if transformation.kind is TransformationKind.EDGE:
            edges.append(
                ProjectedEdge(
                    source=subject,
                    type=transformation.target,
                    target=_object_value(value),
                )
            )
            return
        raise AssertionError(f"unknown transformation kind: {transformation.kind}")

    @staticmethod
    def _handle_unsupported(
        unsupported: list[str],
        predicate: str,
        subject: str,
        profile: ProjectionProfile,
    ) -> None:
        if profile.unsupported_behavior is UnsupportedBehavior.ERROR:
            raise UnsupportedSemanticsError(predicate, subject)
        unsupported.append(predicate)


def _term_key(term: IRI | BlankNode | RDFLiteral) -> str:
    if isinstance(term, IRI):
        return term.value
    if isinstance(term, BlankNode):
        return f"_:{term.label}"
    raise ValueError("a triple subject cannot be a literal")


def _object_value(object: IRI | BlankNode | RDFLiteral) -> str:
    if isinstance(object, RDFLiteral):
        return object.value
    return _term_key(object)


def _edge_key(edge: ProjectedEdge) -> tuple[str, str, str]:
    return edge.source, edge.type, edge.target
