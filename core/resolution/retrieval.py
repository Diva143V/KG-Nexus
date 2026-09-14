"""Baseline candidate retriever."""

from __future__ import annotations

from core.entities.entity import Entity
from core.identifiers.identifier import Identifier
from core.resolution.store import EntityStore


class BlockedRetriever:
    """Retrieves candidates sharing a blocking key with the source."""

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    @property
    def method(self) -> str:
        return self._store.blocking.name

    def retrieve(self, *, source: Entity, activity_id: Identifier) -> list[Entity]:
        key = self._store.blocking.key(source)
        if key is None:
            return []
        return list(self._store.by_blocking_key(key))
