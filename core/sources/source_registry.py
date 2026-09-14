"""Registry of knowledge sources."""

from __future__ import annotations

from collections.abc import Iterable

from core.identifiers.identifier import Identifier
from core.resources.source import Source


class SourceRegistry:
    """Tracks registered sources by identifier."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def register(self, source: Source) -> None:
        key = source.id.canonical
        if key in self._sources:
            raise ValueError(f"duplicate source registered: {key}")
        self._sources[key] = source

    def get(self, source_id: Identifier) -> Source | None:
        return self._sources.get(source_id.canonical)

    def iter_sources(self) -> Iterable[Source]:
        return self._sources.values()
