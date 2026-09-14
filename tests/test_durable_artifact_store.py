from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from core.artifacts.errors import ArtifactIntegrityError
from core.identifiers.identifier import Identifier
from core.resources.artifact import ArtifactKind
from infrastructure.storage.artifact_store import DurableArtifactStore
from infrastructure.storage.graph_store import GraphStore


def _seed_release(db_path, release_id: str = "rel-001") -> Identifier:
    """Pre-create a release row so artifact FK constraints are satisfied."""
    gs = GraphStore(db_path)
    gs.save_release(
        release_id,
        {"type": "test_release", "created_at": datetime.now(UTC).isoformat()},
    )
    return Identifier(namespace="release", value=release_id)


def test_artifact_store_roundtrip(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    rel_id = _seed_release(db_path)
    store = DurableArtifactStore(db_path)
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)

    data = b"Gene: TP53 | Variant: R175H | Significance: Pathogenic"
    artifact = store.store(
        content=data,
        source_release_id=rel_id,
        media_type="text/plain",
        name="tp53_variant.txt",
        kind=ArtifactKind.DOCUMENT,
        retrieved_at=now,
    )

    assert artifact.id.namespace == "artifact"
    assert len(artifact.sha256) == 64
    assert artifact.size_bytes == len(data)

    retrieved = store.get(artifact.id)
    assert retrieved is not None
    assert retrieved == artifact

    content = store.get_content(artifact.id)
    assert content == data

    # Verify integrity passes
    store.verify_integrity(artifact.id)


def test_artifact_store_deduplication(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    rel_id = _seed_release(db_path)
    store = DurableArtifactStore(db_path)
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)

    data = b"Duplicate Content"
    first = store.store(
        content=data,
        source_release_id=rel_id,
        media_type="text/plain",
        retrieved_at=now,
    )
    second = store.store(
        content=data,
        source_release_id=rel_id,
        media_type="text/plain",
        retrieved_at=now,
    )

    assert first.id == second.id
    assert first.sha256 == second.sha256

    artifacts = list(store.iter_artifacts())
    assert len(artifacts) == 1


def test_artifact_store_verify_integrity_failure_on_corrupted_blob(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    rel_id = _seed_release(db_path)
    store = DurableArtifactStore(db_path)
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)

    data = b"Original valid data"
    artifact = store.store(
        content=data,
        source_release_id=rel_id,
        media_type="text/plain",
        retrieved_at=now,
    )

    # Intentionally corrupt the BLOB in SQLite
    con = sqlite3.connect(db_path)
    con.execute(
        "UPDATE artifacts SET content = ? WHERE id = ?",
        (sqlite3.Binary(b"Tampered corrupted data"), artifact.id.canonical),
    )
    con.commit()
    con.close()

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        store.verify_integrity(artifact.id)

    assert "digest mismatch" in str(exc_info.value).lower()


def test_artifact_store_persistence_across_instances(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    rel_id = _seed_release(db_path)
    store1 = DurableArtifactStore(db_path)
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)

    data = b"Persisted content"
    artifact = store1.store(
        content=data,
        source_release_id=rel_id,
        media_type="text/plain",
        retrieved_at=now,
    )

    store2 = DurableArtifactStore(db_path)
    retrieved = store2.get(artifact.id)
    assert retrieved is not None
    assert retrieved.sha256 == artifact.sha256
    assert store2.get_content(artifact.id) == data


def test_capstone_validation_blocks_missing_artifact(tmp_path):
    db_path = tmp_path / "graph.sqlite3"
    graph_store = GraphStore(db_path)
    payload = {"fusion_run": {"fusion_run_id": "run-1"}}

    # Releasing with missing artifact id raises ValueError
    with pytest.raises(ValueError) as exc_info:
        graph_store.save_release(
            "release-1",
            payload,
            artifact_ids=["artifact:nonexistent_sha256_hash_value"],
        )
    assert "Referenced artifact not found" in str(exc_info.value)
