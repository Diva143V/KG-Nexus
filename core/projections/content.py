"""Projection content: the output a projection produces from RDF."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class ProjectedNode(BaseModel):
    """A node projected from RDF content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    properties: dict[str, str] = Field(default_factory=dict)


class ProjectedEdge(BaseModel):
    """An edge projected from RDF content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    type: str = Field(min_length=1)
    target: str = Field(min_length=1)
    properties: dict[str, str] = Field(default_factory=dict)


class ProjectionContent(BaseModel):
    """A deterministically ordered projection of authoritative RDF.

    Dropped and unsupported semantics are audited on the content itself:
    they are the *declared* omissions, so nothing is ever dropped silently.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: Identifier
    profile: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    nodes: tuple[ProjectedNode, ...] = Field(default_factory=tuple)
    edges: tuple[ProjectedEdge, ...] = Field(default_factory=tuple)
    dropped_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def digest(self) -> str:
        """Deterministic SHA-256 over the projection content.

        Ordering is fixed by the content model, so identical logical
        projections produce identical digests regardless of how they were
        built.
        """
        payload = {
            "profile": self.profile,
            "profile_version": self.profile_version,
            "nodes": [_node_dump(node) for node in self.nodes],
            "edges": [_edge_dump(edge) for edge in self.edges],
            "dropped_semantics": list(self.dropped_semantics),
            "unsupported_semantics": list(self.unsupported_semantics),
        }
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _node_dump(node: ProjectedNode) -> dict[str, object]:
    return {
        "key": node.key,
        "kind": node.kind,
        "properties": node.properties,
    }


def _edge_dump(edge: ProjectedEdge) -> dict[str, object]:
    return {
        "source": edge.source,
        "type": edge.type,
        "target": edge.target,
        "properties": edge.properties,
    }
