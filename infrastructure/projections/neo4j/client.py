"""Neo4j client abstraction and deterministic in-memory implementation.

``Neo4jClient`` is the boundary where a real driver (e.g. the official
Neo4j Python driver) plugs in. ``MemoryNeo4jClient`` is the deterministic
in-memory implementation used by tests and demos.

The client is a pure implementation detail of this backend. Cypher is never
authoritative and Core never sees it. The client scopes all content by a
store key (the projection's candidate name), so candidates and retained
projections coexist until explicitly deleted.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from infrastructure.projections.neo4j.errors import Neo4jClientError
from infrastructure.projections.neo4j.schema import Neo4jNode, Neo4jRelationship


@runtime_checkable
class Neo4jClient(Protocol):
    """Graph-store operations used by the Neo4j projection backend."""

    @property
    def client_name(self) -> str:
        """Stable identifier for this client implementation."""
        ...

    def has_projection(self, store_key: str) -> bool:
        """Whether content exists under ``store_key``."""
        ...

    def create_node(self, store_key: str, node: Neo4jNode) -> None:
        """Create a node under ``store_key``."""
        ...

    def create_relationship(self, store_key: str, rel: Neo4jRelationship) -> None:
        """Create a relationship under ``store_key``."""
        ...

    def get_node(self, store_key: str, node_id: str) -> Neo4jNode | None:
        """Return a node by its id, if present."""
        ...

    def get_relationship(self, store_key: str, rel_id: str) -> Neo4jRelationship | None:
        """Return a relationship by its id, if present."""
        ...

    def all_nodes(self, store_key: str) -> tuple[Neo4jNode, ...]:
        """All nodes under ``store_key``, sorted by id."""
        ...

    def all_relationships(self, store_key: str) -> tuple[Neo4jRelationship, ...]:
        """All relationships under ``store_key``, sorted by id."""
        ...

    def node_count(self, store_key: str) -> int:
        """Number of nodes under ``store_key``."""
        ...

    def relationship_count(self, store_key: str) -> int:
        """Number of relationships under ``store_key``."""
        ...

    def activate(self, store_key: str) -> None:
        """Atomically promote the candidate under ``store_key`` to active.

        The content itself is never moved or deleted; activation flips the
        store's active pointer. Previously active content remains in place
        and can be restored by a later rollback.
        """
        ...

    def active_projection(self) -> str | None:
        """Store key of the currently active projection, if any."""
        ...

    def rollback(self, store_key: str) -> None:
        """Deactivate the projection under ``store_key``.

        Retained content is left untouched so it can be restored without
        rebuilding.
        """
        ...

    def delete_projection(self, store_key: str) -> None:
        """Delete all content under ``store_key``, if present."""
        ...


class MemoryNeo4jClient:
    """Deterministic in-memory Neo4j-like graph store."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Neo4jNode]] = {}
        self._relationships: dict[str, dict[str, Neo4jRelationship]] = {}
        self._active: str | None = None

    @property
    def client_name(self) -> str:
        return "memory-neo4j"

    def has_projection(self, store_key: str) -> bool:
        return store_key in self._nodes

    def create_node(self, store_key: str, node: Neo4jNode) -> None:
        self._ensure(store_key)
        if node.id in self._nodes[store_key]:
            raise Neo4jClientError(f"node already exists: {node.id}")
        self._nodes[store_key][node.id] = node

    def create_relationship(self, store_key: str, rel: Neo4jRelationship) -> None:
        self._ensure(store_key)
        if rel.id in self._relationships[store_key]:
            raise Neo4jClientError(f"relationship already exists: {rel.id}")
        if rel.start_node_id not in self._nodes[store_key]:
            raise Neo4jClientError(f"start node missing: {rel.start_node_id}")
        if rel.end_node_id not in self._nodes[store_key]:
            raise Neo4jClientError(f"end node missing: {rel.end_node_id}")
        self._relationships[store_key][rel.id] = rel

    def get_node(self, store_key: str, node_id: str) -> Neo4jNode | None:
        return self._nodes.get(store_key, {}).get(node_id)

    def get_relationship(self, store_key: str, rel_id: str) -> Neo4jRelationship | None:
        return self._relationships.get(store_key, {}).get(rel_id)

    def all_nodes(self, store_key: str) -> tuple[Neo4jNode, ...]:
        return tuple(sorted(self._nodes.get(store_key, {}).values(), key=lambda n: n.id))

    def all_relationships(self, store_key: str) -> tuple[Neo4jRelationship, ...]:
        return tuple(sorted(self._relationships.get(store_key, {}).values(), key=lambda r: r.id))

    def node_count(self, store_key: str) -> int:
        return len(self._nodes.get(store_key, {}))

    def relationship_count(self, store_key: str) -> int:
        return len(self._relationships.get(store_key, {}))

    def activate(self, store_key: str) -> None:
        if store_key not in self._nodes:
            raise Neo4jClientError(f"no candidate to activate: {store_key}")
        self._active = store_key

    def active_projection(self) -> str | None:
        return self._active

    def rollback(self, store_key: str) -> None:
        if self._active == store_key:
            self._active = None

    def delete_projection(self, store_key: str) -> None:
        self._nodes.pop(store_key, None)
        self._relationships.pop(store_key, None)
        if self._active == store_key:
            self._active = None

    def _ensure(self, store_key: str) -> None:
        if store_key not in self._nodes:
            self._nodes[store_key] = {}
        if store_key not in self._relationships:
            self._relationships[store_key] = {}


def conforms_to_client(client: object) -> bool:
    """True when ``client`` implements the Neo4jClient contract."""
    return isinstance(client, Neo4jClient)
