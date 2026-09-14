"""Immutable, content-addressed artifact storage."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from core.artifacts.checksum import ArtifactChecksumService
from core.identifiers.identifier import Identifier
from core.resources.artifact import Artifact, ArtifactKind


class ArtifactStore:
    """Stores artifacts by content address.

    Artifacts are immutable: identical content reuses the existing
    artifact record, and new content always creates a new artifact.
    Existing artifacts are never overwritten.
    """

    def __init__(self, checksum: ArtifactChecksumService) -> None:
        self._checksum = checksum
        self._by_sha: dict[str, Artifact] = {}
        self._by_id: dict[str, Artifact] = {}

    def store(
        self,
        *,
        content: bytes,
        source_release_id: Identifier,
        media_type: str,
        name: str | None = None,
        kind: ArtifactKind = ArtifactKind.OTHER,
        retrieved_at: datetime,
    ) -> Artifact:
        """Store ``content`` and return an immutable artifact record.

        If identical content was stored before, the existing artifact is
        returned unchanged (reused/referenced). Otherwise a new artifact
        is created with a content-derived identifier.
        """
        sha = self._checksum.sha256(content)
        existing = self._by_sha.get(sha)
        if existing is not None:
            return existing
        artifact = Artifact(
            id=Identifier(namespace="artifact", value=sha),
            source_release_id=source_release_id,
            kind=kind,
            name=name,
            media_type=media_type,
            sha256=sha,
            size_bytes=self._checksum.size_bytes(content),
            retrieved_at=retrieved_at,
        )
        self._by_sha[sha] = artifact
        self._by_id[artifact.id.canonical] = artifact
        return artifact

    def get(self, artifact_id: Identifier) -> Artifact | None:
        return self._by_id.get(artifact_id.canonical)

    def by_sha256(self, sha: str) -> Artifact | None:
        return self._by_sha.get(sha)

    def iter_artifacts(self) -> Iterable[Artifact]:
        return self._by_id.values()
