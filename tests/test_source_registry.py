from __future__ import annotations

import pytest

from core.resources.source import Source, SourceKind
from core.sources.source_registry import SourceRegistry
from tests.helpers import ident


def make_source(source_id: str = "s-1") -> Source:
    return Source(
        id=ident("source", source_id),
        label="Some DB",
        kind=SourceKind.DATABASE,
    )


def test_register_and_get() -> None:
    registry = SourceRegistry()
    source = make_source()
    registry.register(source)
    assert registry.get(source.id) is source


def test_register_duplicate_rejected() -> None:
    registry = SourceRegistry()
    registry.register(make_source())
    with pytest.raises(ValueError):
        registry.register(make_source())


def test_get_missing_returns_none() -> None:
    registry = SourceRegistry()
    assert registry.get(ident("source", "missing")) is None


def test_iter_sources() -> None:
    registry = SourceRegistry()
    first = make_source("s-1")
    second = make_source("s-2")
    registry.register(first)
    registry.register(second)
    assert {source.id for source in registry.iter_sources()} == {
        first.id,
        second.id,
    }
