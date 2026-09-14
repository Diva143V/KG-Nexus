from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.resources.artifact import Artifact, ArtifactKind
from core.resources.parsed_record import ParsedRecord, RecordStatus
from core.resources.resource import Resource
from core.resources.source import Source, SourceKind
from core.resources.source_release import SourceRelease
from tests.helpers import ident, utc


def test_resource_constructed() -> None:
    resource = Resource(id=ident("res", "r-1"), label="A resource")
    assert resource.label == "A resource"


def test_resource_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Resource(id=ident("res", "r-1"), label="x", unexpected=True)


def test_source_constructed() -> None:
    source = Source(id=ident("source", "s-1"), label="Some DB", kind=SourceKind.DATABASE)
    assert source.kind == SourceKind.DATABASE


def test_source_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Source(id=ident("source", "s-1"), label="x", kind="not-a-kind")


def test_source_release_constructed() -> None:
    release = SourceRelease(
        id=ident("release", "r-1"),
        source_id=ident("source", "s-1"),
        version="2026.1",
    )
    assert release.version == "2026.1"


def test_source_release_requires_version() -> None:
    with pytest.raises(ValidationError):
        SourceRelease(
            id=ident("release", "r-1"),
            source_id=ident("source", "s-1"),
            version="",
        )


def test_artifact_constructed() -> None:
    artifact = Artifact(
        id=ident("artifact", "a-1"),
        source_release_id=ident("release", "r-1"),
        kind=ArtifactKind.DATASET,
        name="export.json",
        media_type="application/ld+json",
        sha256="ab" * 32,
        size_bytes=42,
        retrieved_at=utc(2026, 1, 1),
    )
    assert artifact.name == "export.json"
    assert artifact.sha256 == "ab" * 32
    assert artifact.size_bytes == 42


def test_artifact_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Artifact(
            id=ident("artifact", "a-1"),
            source_release_id=ident("release", "r-1"),
            kind="bogus",
            name="x",
            media_type="text/csv",
            sha256="ab" * 32,
            size_bytes=1,
            retrieved_at=utc(2026, 1, 1),
        )


def test_artifact_rejects_invalid_sha256() -> None:
    with pytest.raises(ValidationError):
        Artifact(
            id=ident("artifact", "a-1"),
            source_release_id=ident("release", "r-1"),
            media_type="text/csv",
            sha256="not-a-digest",
            size_bytes=1,
            retrieved_at=utc(2026, 1, 1),
        )


def test_artifact_is_immutable() -> None:
    artifact = Artifact(
        id=ident("artifact", "a-1"),
        source_release_id=ident("release", "r-1"),
        media_type="text/csv",
        sha256="ab" * 32,
        size_bytes=1,
        retrieved_at=utc(2026, 1, 1),
    )
    with pytest.raises((ValueError, TypeError)):
        artifact.sha256 = "cd" * 32


def test_parsed_record_constructed() -> None:
    record = ParsedRecord(
        id=ident("record", "p-1"),
        artifact_id=ident("artifact", "a-1"),
        record_type="csv_row",
        parsed_at=utc(2026, 1, 1),
    )
    assert record.status == RecordStatus.PARSED
    assert record.errors == []


def test_parsed_record_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        ParsedRecord(
            id=ident("record", "p-1"),
            artifact_id=ident("artifact", "a-1"),
            record_type="x",
            status="nope",
            parsed_at=utc(2026, 1, 1),
        )
