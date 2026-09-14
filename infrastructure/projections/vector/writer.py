"""Deterministic serialization for the vector projection.

This module is the serialization boundary of the vector backend: everything
stored or read back goes through these functions. Vectors and manifests are
serialized as canonical JSON (sorted keys, compact separators), so identical
content always produces identical bytes and identical digests. Parse failures
are surfaced as ``None`` through the ``try_*`` helpers so validation,
reconciliation, and smoke tests fail cleanly instead of raising.
"""

from __future__ import annotations

import json
from hashlib import sha256

from infrastructure.projections.vector.embedder import EmbeddingModel
from infrastructure.projections.vector.manifest import VectorManifest
from infrastructure.projections.vector.models import EmbeddedItem


def manifest_bytes(manifest: VectorManifest) -> bytes:
    """Serialize a manifest to canonical JSON bytes."""
    return _json_bytes(manifest.model_dump())


def items_bytes(items: tuple[EmbeddedItem, ...]) -> bytes:
    """Serialize embedded items to canonical JSON bytes."""
    return _json_bytes([item.model_dump() for item in items])


def manifest_from_bytes(data: bytes) -> VectorManifest:
    """Parse a manifest from canonical JSON bytes."""
    return VectorManifest.model_validate(json.loads(data.decode("utf-8")))


def items_from_bytes(data: bytes) -> tuple[EmbeddedItem, ...]:
    """Parse embedded items from canonical JSON bytes."""
    raw = json.loads(data.decode("utf-8"))
    return tuple(EmbeddedItem.model_validate(entry) for entry in raw)


def try_manifest_from_bytes(data: bytes) -> VectorManifest | None:
    """Parse a manifest, returning None when it is unreadable."""
    try:
        return manifest_from_bytes(data)
    except (ValueError, json.JSONDecodeError):
        return None


def try_items_from_bytes(data: bytes) -> tuple[EmbeddedItem, ...] | None:
    """Parse embedded items, returning None when they are unreadable."""
    try:
        return items_from_bytes(data)
    except (ValueError, json.JSONDecodeError):
        return None


def embedding_digest(items: tuple[EmbeddedItem, ...]) -> str:
    """Stable digest over the exact vector content, keyed by item key."""
    canonical = _json_bytes([(item.key, item.vector) for item in items])
    return sha256(canonical).hexdigest()


def manifest_for(
    *,
    model: EmbeddingModel,
    release_id: str,
    items: tuple[EmbeddedItem, ...],
) -> VectorManifest:
    """Build the manifest recorded for a derived projection."""
    return VectorManifest(
        model_id=model.model_id,
        model_version=model.model_version,
        dimensions=model.dimensions,
        embedding_config=model.embedding_config,
        release_id=release_id,
        record_count=len(items),
        embedding_digest=embedding_digest(items),
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
