"""In-memory entity store with blocking-key indexes."""

from __future__ import annotations

from collections.abc import Iterable

from core.entities.entity import Entity
from core.identifiers.identifier import Identifier
from core.resolution.blocking import BlockingKey


class EntityStore:
    """Registers entities and indexes them by a single blocking key."""

    def __init__(self, blocking: BlockingKey) -> None:
        self._blocking = blocking
        self._by_id: dict[str, Entity] = {}
        self._index: dict[str, list[Entity]] = {}

    @property
    def blocking(self) -> BlockingKey:
        return self._blocking

    def register(self, entity: Entity) -> None:
        key = entity.id.canonical
        if key in self._by_id:
            raise ValueError(f"duplicate entity registered: {key}")
        self._by_id[key] = entity
        block_key = self._blocking.key(entity)
        if block_key is not None:
            self._index.setdefault(block_key, []).append(entity)

    def get(self, entity_id: Identifier) -> Entity | None:
        return self._by_id.get(entity_id.canonical)

    def by_blocking_key(self, key: str) -> tuple[Entity, ...]:
        return tuple(self._index.get(key, ()))

    def iter_entities(self) -> Iterable[Entity]:
        return self._by_id.values()
