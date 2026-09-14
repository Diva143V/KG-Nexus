"""Durable, SQLite-backed content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.artifacts.checksum import ArtifactChecksumService
from core.artifacts.errors import ArtifactIntegrityError
from core.identifiers.identifier import Identifier
from core.resources.artifact import Artifact, ArtifactKind
from infrastructure.storage.migration_runner import MigrationRunner


class DurableArtifactStore:
    """Durable, SQLite-backed store for content-addressed artifacts.

    Persists raw artifact bytes as BLOBs with SHA-256 content addressing,
    strict fail-closed integrity validation, and deduplication.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        checksum: ArtifactChecksumService | None = None,
    ) -> None:
        configured_path: str | Path = (
            database_path
            if database_path is not None
            else os.getenv("HYBRID_KG_DB_PATH", "data/hybrid_kg.sqlite3")
        )
        self.database_path = Path(configured_path)
        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._checksum = checksum or ArtifactChecksumService()
        self.migration_runner = MigrationRunner(self.database_path)
        self.migration_runner.migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if str(self.database_path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _session(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
        """Store content BLOB and return an immutable artifact record.

        Identical content reuses existing record (content deduplication).
        The dedup check and INSERT are performed under a single lock
        acquisition to prevent TOCTOU races.
        """
        sha = self._checksum.sha256(content)
        artifact_id = Identifier(namespace="artifact", value=sha)
        size_bytes = self._checksum.size_bytes(content)
        retrieved_at_iso = retrieved_at.isoformat()
        kind_val = kind.value if isinstance(kind, ArtifactKind) else str(kind)

        with self._lock, self._session() as connection:
            # Dedup check and INSERT are atomic under the same lock+connection.
            row = connection.execute(
                """
                SELECT id, sha256, media_type, name, kind, size_bytes,
                       retrieved_at, source_release_id
                FROM artifacts WHERE sha256 = ?
                """,
                (sha,),
            ).fetchone()
            if row is not None:
                return Artifact(
                    id=Identifier.parse(row["id"]),
                    source_release_id=Identifier(
                        namespace="release", value=row["source_release_id"]
                    ),
                    kind=ArtifactKind(row["kind"]),
                    name=row["name"],
                    media_type=row["media_type"],
                    sha256=row["sha256"],
                    size_bytes=int(row["size_bytes"]),
                    retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
                )

            connection.execute(
                """
                INSERT INTO artifacts (
                    id, sha256, media_type, name, kind, size_bytes,
                    retrieved_at, content, source_release_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id.canonical,
                    sha,
                    media_type,
                    name,
                    kind_val,
                    size_bytes,
                    retrieved_at_iso,
                    sqlite3.Binary(content),
                    source_release_id.value,  # bare value — matches releases.release_id FK
                ),
            )
            connection.commit()

        return Artifact(
            id=artifact_id,
            source_release_id=source_release_id,
            kind=kind,
            name=name,
            media_type=media_type,
            sha256=sha,
            size_bytes=size_bytes,
            retrieved_at=retrieved_at,
        )

    def get(self, artifact_id: Identifier) -> Artifact | None:
        with self._lock, self._session() as connection:
            row = connection.execute(
                """
                SELECT id, sha256, media_type, name, kind, size_bytes,
                       retrieved_at, source_release_id
                FROM artifacts WHERE id = ?
                """,
                (artifact_id.canonical,),
            ).fetchone()
            if row is None:
                return None
            return Artifact(
                id=artifact_id,
                source_release_id=Identifier(namespace="release", value=row["source_release_id"]),
                kind=ArtifactKind(row["kind"]),
                name=row["name"],
                media_type=row["media_type"],
                sha256=row["sha256"],
                size_bytes=int(row["size_bytes"]),
                retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            )

    def get_content(self, artifact_id: Identifier) -> bytes | None:
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT content FROM artifacts WHERE id = ?",
                (artifact_id.canonical,),
            ).fetchone()
            if row is None:
                return None
            return bytes(row["content"])

    def by_sha256(self, sha: str) -> Artifact | None:
        with self._lock, self._session() as connection:
            row = connection.execute(
                """
                SELECT id, sha256, media_type, name, kind, size_bytes,
                       retrieved_at, source_release_id
                FROM artifacts WHERE sha256 = ?
                """,
                (sha,),
            ).fetchone()
            if row is None:
                return None
            return Artifact(
                id=Identifier.parse(row["id"]),
                source_release_id=Identifier(namespace="release", value=row["source_release_id"]),
                kind=ArtifactKind(row["kind"]),
                name=row["name"],
                media_type=row["media_type"],
                sha256=row["sha256"],
                size_bytes=int(row["size_bytes"]),
                retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            )

    def verify_integrity(self, artifact_id: Identifier) -> None:
        """Verify stored content matches recorded SHA-256.

        Raises ArtifactIntegrityError on mismatch (strict fail-closed).
        """
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT sha256, content FROM artifacts WHERE id = ?",
                (artifact_id.canonical,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Artifact {artifact_id.canonical} not found")
            content_bytes = bytes(row["content"])
            recorded_sha = row["sha256"]
            actual_sha = hashlib.sha256(content_bytes).hexdigest()
            if actual_sha != recorded_sha:
                raise ArtifactIntegrityError(
                    f"Artifact {artifact_id.canonical} digest mismatch: "
                    f"recorded {recorded_sha}, actual {actual_sha}"
                )

    def iter_artifacts(self) -> Iterable[Artifact]:
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, sha256, media_type, name, kind, size_bytes,
                       retrieved_at, source_release_id, created_at
                FROM artifacts ORDER BY created_at ASC
                """
            ).fetchall()
            for row in rows:
                yield Artifact(
                    id=Identifier.parse(row["id"]),
                    source_release_id=Identifier(
                        namespace="release", value=row["source_release_id"]
                    ),
                    kind=ArtifactKind(row["kind"]),
                    name=row["name"],
                    media_type=row["media_type"],
                    sha256=row["sha256"],
                    size_bytes=int(row["size_bytes"]),
                    retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
                )
