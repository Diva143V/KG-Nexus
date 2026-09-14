"""Deterministic serialization for the search projection.

This module is the serialization boundary of the search backend: everything
stored or read back goes through these functions. Documents and manifests are
serialized as canonical JSON (sorted keys, compact separators), so identical
content always produces identical bytes and identical digests. Parse failures
are surfaced as ``None`` through the ``try_*`` helpers so validation,
reconciliation, and smoke tests fail cleanly instead of raising.
"""

from __future__ import annotations

import json
from hashlib import sha256

from infrastructure.projections.search.documents import SearchDocument
from infrastructure.projections.search.index import SearchEngine
from infrastructure.projections.search.manifest import SearchManifest


def manifest_bytes(manifest: SearchManifest) -> bytes:
    """Serialize a manifest to canonical JSON bytes."""
    return _json_bytes(manifest.model_dump())


def documents_bytes(documents: tuple[SearchDocument, ...]) -> bytes:
    """Serialize search documents to canonical JSON bytes."""
    return _json_bytes([document.model_dump() for document in documents])


def manifest_from_bytes(data: bytes) -> SearchManifest:
    """Parse a manifest from canonical JSON bytes."""
    return SearchManifest.model_validate(json.loads(data.decode("utf-8")))


def documents_from_bytes(data: bytes) -> tuple[SearchDocument, ...]:
    """Parse search documents from canonical JSON bytes."""
    raw = json.loads(data.decode("utf-8"))
    return tuple(SearchDocument.model_validate(entry) for entry in raw)


def try_manifest_from_bytes(data: bytes) -> SearchManifest | None:
    """Parse a manifest, returning None when it is unreadable."""
    try:
        return manifest_from_bytes(data)
    except (ValueError, json.JSONDecodeError):
        return None


def try_documents_from_bytes(data: bytes) -> tuple[SearchDocument, ...] | None:
    """Parse search documents, returning None when they are unreadable."""
    try:
        return documents_from_bytes(data)
    except (ValueError, json.JSONDecodeError):
        return None


def content_digest(documents: tuple[SearchDocument, ...]) -> str:
    """Stable digest over the exact document content, keyed by document id."""
    canonical = _json_bytes([(document.doc_id, document.text) for document in documents])
    return sha256(canonical).hexdigest()


def manifest_for(
    *,
    engine: SearchEngine,
    release_id: str,
    documents: tuple[SearchDocument, ...],
) -> SearchManifest:
    """Build the manifest recorded for a derived projection."""
    return SearchManifest(
        engine_id=engine.engine_id,
        engine_version=engine.engine_version,
        engine_config=engine.engine_config,
        release_id=release_id,
        record_count=len(documents),
        content_digest=content_digest(documents),
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
