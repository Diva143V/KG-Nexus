from __future__ import annotations

from datetime import datetime

import pytest

from core.artifacts.artifact_store import ArtifactStore
from core.artifacts.checksum import ArtifactChecksumService
from tests.helpers import ident, utc

CONTENT = b'{"@graph": [{"name": "alice"}]}'
RETRIEVED_AT = utc(2026, 1, 1)


def build_store() -> ArtifactStore:
    return ArtifactStore(ArtifactChecksumService())


def store(
    store: ArtifactStore,
    content: bytes = CONTENT,
    *,
    name: str = "payload.json",
    media_type: str = "application/ld+json",
    release: str = "rel-1",
    retrieved_at: datetime = RETRIEVED_AT,
):
    return store.store(
        content=content,
        source_release_id=ident("release", release),
        media_type=media_type,
        name=name,
        retrieved_at=retrieved_at,
    )


def test_store_records_digest_fields() -> None:
    artifact = store(build_store())
    assert artifact.media_type == "application/ld+json"
    assert artifact.sha256 == ArtifactChecksumService().sha256(CONTENT)
    assert artifact.size_bytes == len(CONTENT)
    assert artifact.source_release_id == ident("release", "rel-1")


def test_store_uses_content_derived_id() -> None:
    artifact = store(build_store())
    assert artifact.id.namespace == "artifact"
    assert artifact.id.value == ArtifactChecksumService().sha256(CONTENT)


def test_identical_content_reuses_existing_artifact() -> None:
    artifact_store = build_store()
    first = store(artifact_store)
    second = store(artifact_store, name="renamed.json", release="rel-2")
    assert first.id == second.id
    assert second.name == first.name
    assert len(list(artifact_store.iter_artifacts())) == 1


def test_different_content_creates_new_artifact() -> None:
    artifact_store = build_store()
    first = store(artifact_store)
    second = store(artifact_store, content=b"different")
    assert first.id != second.id
    assert len(list(artifact_store.iter_artifacts())) == 2


def test_store_never_overwrites() -> None:
    artifact_store = build_store()
    first = store(artifact_store)
    artifact_store.store(
        content=CONTENT,
        source_release_id=ident("release", "rel-9"),
        media_type="application/ld+json",
        name="overwrite.json",
        retrieved_at=utc(2026, 1, 2),
    )
    assert artifact_store.get(first.id) is first


def test_get_by_id_and_sha() -> None:
    artifact_store = build_store()
    artifact = store(artifact_store)
    assert artifact_store.get(artifact.id) is artifact
    assert artifact_store.by_sha256(artifact.sha256) is artifact


def test_missing_artifact_returns_none() -> None:
    artifact_store = build_store()
    assert artifact_store.get(ident("artifact", "missing")) is None
    assert artifact_store.by_sha256("00" * 32) is None


def test_stored_artifacts_are_immutable() -> None:
    artifact = store(build_store())
    with pytest.raises((ValueError, TypeError)):
        artifact.size_bytes = 999
