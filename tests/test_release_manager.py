from __future__ import annotations

import pytest

from core.artifacts.artifact_store import ArtifactStore
from core.artifacts.checksum import ArtifactChecksumService
from core.parsing.parser_registry import ParserRegistry
from core.resources.source import Source, SourceKind
from core.resources.source_release import SourceRelease
from core.sources.errors import UnknownReleaseError, UnknownSourceError
from core.sources.release_manager import IngestionStatus, SourceReleaseManager
from core.sources.source_registry import SourceRegistry
from sdk.source_adapter import FetchResult, SourceAdapter
from tests.helpers import ident

TURTLE = b"@prefix ex: <http://example.com/> .\nex:alice ex:knows ex:bob .\n"
CSV = b"gene,value\ng1,1.5\n"
JSONLD = b'{"@graph": [{"name": "alice"}]}'


class StaticAdapter:
    def __init__(self, results: list[FetchResult]) -> None:
        self._results = results

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return list(self._results)


class FailingAdapter:
    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        raise RuntimeError("boom")


def build_manager(
    *,
    source_id: str = "s-1",
    adapter: SourceAdapter | None = None,
) -> tuple[SourceRegistry, SourceReleaseManager]:
    registry = SourceRegistry()
    registry.register(
        Source(
            id=ident("source", source_id),
            label="Some DB",
            kind=SourceKind.DATABASE,
        )
    )
    manager = SourceReleaseManager(
        registry=registry,
        artifact_store=ArtifactStore(ArtifactChecksumService()),
        parser_registry=ParserRegistry(),
        adapter=adapter or StaticAdapter([]),
    )
    return registry, manager


def fetch_result(name: str, media_type: str, content: bytes) -> FetchResult:
    return FetchResult(name=name, media_type=media_type, content=content)


def test_create_release_requires_registered_source() -> None:
    registry = SourceRegistry()
    manager = SourceReleaseManager(
        registry=registry,
        artifact_store=ArtifactStore(ArtifactChecksumService()),
        parser_registry=ParserRegistry(),
        adapter=StaticAdapter([]),
    )
    with pytest.raises(UnknownSourceError):
        manager.create_release(source_id=ident("source", "missing"), version="1.0")


def test_create_release_deterministic_id_and_duplicate_rejection() -> None:
    _, manager = build_manager()
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    assert release.id == ident("release", "s-1:1.0")
    with pytest.raises(ValueError):
        manager.create_release(source_id=ident("source", "s-1"), version="1.0")


def test_ingest_unknown_release_raises() -> None:
    _, manager = build_manager()
    with pytest.raises(UnknownReleaseError):
        manager.ingest(
            SourceRelease(
                id=ident("release", "nope"),
                source_id=ident("source", "s-1"),
                version="1.0",
            )
        )


def test_ingest_complete() -> None:
    _, manager = build_manager(
        adapter=StaticAdapter(
            [
                fetch_result("triples.ttl", "text/turtle", TURTLE),
                fetch_result("genes.csv", "text/csv", CSV),
            ]
        )
    )
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    result = manager.ingest(release)
    assert result.status == IngestionStatus.COMPLETE
    assert len(result.artifacts) == 2
    assert len(result.records) == 2
    assert result.errors == ()


def test_ingest_partial_when_artifact_unparseable() -> None:
    _, manager = build_manager(
        adapter=StaticAdapter(
            [
                fetch_result("triples.ttl", "text/turtle", TURTLE),
                fetch_result("data.xml", "application/xml", b"<x/>"),
            ]
        )
    )
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    result = manager.ingest(release)
    assert result.status == IngestionStatus.PARTIAL
    assert len(result.artifacts) == 2
    assert result.errors


def test_ingest_partial_when_records_fail() -> None:
    _, manager = build_manager(
        adapter=StaticAdapter([fetch_result("bad.csv", "text/csv", b"a,b,c\n1,2\n")])
    )
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    result = manager.ingest(release)
    assert result.status == IngestionStatus.PARTIAL
    assert len(result.artifacts) == 1
    assert len(result.records) == 1
    assert result.errors


def test_ingest_failed_when_fetch_raises() -> None:
    _, manager = build_manager(adapter=FailingAdapter())
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    result = manager.ingest(release)
    assert result.status == IngestionStatus.FAILED
    assert result.artifacts == ()
    assert result.errors


def test_ingest_reuses_identical_content_across_releases() -> None:
    _, manager = build_manager(adapter=StaticAdapter([fetch_result("genes.csv", "text/csv", CSV)]))
    first = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    second = manager.create_release(source_id=ident("source", "s-1"), version="2.0")
    first_result = manager.ingest(first)
    second_result = manager.ingest(second)
    assert first_result.artifacts == second_result.artifacts
    assert first_result.status == IngestionStatus.COMPLETE
    assert second_result.status == IngestionStatus.COMPLETE


def test_ingestion_for_returns_result() -> None:
    _, manager = build_manager(adapter=StaticAdapter([fetch_result("genes.csv", "text/csv", CSV)]))
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    result = manager.ingest(release)
    assert manager.ingestion_for(release.id) is result
    assert manager.ingestion_for(ident("release", "missing")) is None


def test_iter_releases() -> None:
    _, manager = build_manager()
    release = manager.create_release(source_id=ident("source", "s-1"), version="1.0")
    assert list(manager.iter_releases()) == [release]
