"""Durable, SQLite-backed projection manifest storage."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.projections import ProjectionManifestRecord
from infrastructure.storage.migration_runner import MigrationRunner


class DurableProjectionStore:
    """Durable, SQLite-backed store for projection manifests and metadata.

    Persists projection build outputs, schema/model versions, input/output digests,
    record counts, and lifecycle transitions with foreign keys to releases.
    """

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured_path: str | Path = (
            database_path
            if database_path is not None
            else os.getenv("HYBRID_KG_DB_PATH", "data/hybrid_kg.sqlite3")
        )
        self.database_path = Path(configured_path)
        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
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

    def record_manifest(self, record: ProjectionManifestRecord) -> None:
        """Insert or replace a projection manifest record."""
        with self._lock, self._session() as connection:
            connection.execute(
                """
                INSERT INTO projection_manifests (
                    projection_id, release_id, backend_id, status,
                    schema_version, model_version, input_digest, output_digest,
                    record_count, manifest_json, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(projection_id) DO UPDATE SET
                    status=excluded.status,
                    output_digest=excluded.output_digest,
                    record_count=excluded.record_count,
                    manifest_json=excluded.manifest_json,
                    activated_at=excluded.activated_at
                """,
                (
                    record.projection_id,
                    record.release_id,
                    record.backend_id,
                    record.status,
                    record.schema_version,
                    record.model_version,
                    record.input_digest,
                    record.output_digest,
                    record.record_count,
                    record.manifest_json,
                    record.created_at,
                    record.activated_at,
                ),
            )

    def update_status(
        self,
        projection_id: str,
        status: str,
        *,
        manifest_json: str | None = None,
        activated_at: str | None = None,
    ) -> None:
        """Update status and optionally manifest_json and activated_at for a projection."""
        with self._lock, self._session() as connection:
            if manifest_json is not None and activated_at is not None:
                connection.execute(
                    """
                    UPDATE projection_manifests
                    SET status = ?, manifest_json = ?, activated_at = ?
                    WHERE projection_id = ?
                    """,
                    (status, manifest_json, activated_at, projection_id),
                )
            elif manifest_json is not None:
                connection.execute(
                    """
                    UPDATE projection_manifests
                    SET status = ?, manifest_json = ?
                    WHERE projection_id = ?
                    """,
                    (status, manifest_json, projection_id),
                )
            elif activated_at is not None:
                connection.execute(
                    """
                    UPDATE projection_manifests
                    SET status = ?, activated_at = ?
                    WHERE projection_id = ?
                    """,
                    (status, activated_at, projection_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE projection_manifests
                    SET status = ?
                    WHERE projection_id = ?
                    """,
                    (status, projection_id),
                )

    def get(self, projection_id: str) -> ProjectionManifestRecord | None:
        """Fetch a projection manifest by projection_id."""
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE projection_id = ?
                """,
                (projection_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def get_by_release(self, release_id: str) -> list[ProjectionManifestRecord]:
        """Fetch all projection manifests for a release_id."""
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE release_id = ?
                ORDER BY created_at ASC
                """,
                (release_id,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_active_by_backend(self, backend_id: str) -> ProjectionManifestRecord | None:
        """Fetch the currently active projection for a given backend_id."""
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE backend_id = ? AND status = 'ACTIVE'
                ORDER BY activated_at DESC LIMIT 1
                """,
                (backend_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def get_all_active(self) -> list[ProjectionManifestRecord]:
        """Fetch all currently active projection manifests across all backends."""
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE status = 'ACTIVE'
                ORDER BY activated_at DESC, created_at DESC
                """
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_previous_projection(
        self,
        backend_id: str,
        *,
        exclude_projection_id: str | None = None,
        target_release_id: str | None = None,
    ) -> ProjectionManifestRecord | None:
        """Fetch the prior candidate/retained projection to restore upon rollback."""
        with self._lock, self._session() as connection:
            query = """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE backend_id = ?
                  AND status != 'FAILED'
            """
            params: list[Any] = [backend_id]
            if exclude_projection_id is not None:
                query += " AND projection_id != ?"
                params.append(exclude_projection_id)
            if target_release_id is not None:
                query += " AND release_id = ?"
                params.append(target_release_id)
            query += " ORDER BY COALESCE(activated_at, created_at) DESC, created_at DESC LIMIT 1"

            cursor = connection.execute(query, tuple(params))
            row = cursor.fetchone()
            return self._row_to_record(row) if row is not None else None

    def get_known_backends(self) -> list[str]:
        """Return distinct backend IDs that have recorded projection manifests."""
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                "SELECT DISTINCT backend_id FROM projection_manifests ORDER BY backend_id ASC"
            )
            return [row[0] for row in cursor.fetchall()]

    def rollback_projection(
        self,
        backend_id: str,
        *,
        target_release_id: str | None = None,
    ) -> tuple[ProjectionManifestRecord | None, ProjectionManifestRecord | None]:
        """Atomically demote the active projection to ROLLED_BACK and restore the target/previous projection to ACTIVE."""
        with self._lock, self._session() as connection:
            # 1. Fetch current active projection in the same session
            cur_cursor = connection.execute(
                """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE backend_id = ? AND status = 'ACTIVE'
                ORDER BY activated_at DESC LIMIT 1
                """,
                (backend_id,),
            )
            cur_row = cur_cursor.fetchone()
            current = self._row_to_record(cur_row) if cur_row is not None else None
            demoted_id = current.projection_id if current is not None else None

            # 2. Query target or prior projection in the same session
            query = """
                SELECT projection_id, release_id, backend_id, status,
                       schema_version, model_version, input_digest, output_digest,
                       record_count, manifest_json, created_at, activated_at
                FROM projection_manifests
                WHERE backend_id = ?
                  AND status != 'FAILED'
            """
            params: list[Any] = [backend_id]
            if demoted_id is not None:
                query += " AND projection_id != ?"
                params.append(demoted_id)
            if target_release_id is not None:
                query += " AND release_id = ?"
                params.append(target_release_id)
            query += " ORDER BY COALESCE(activated_at, created_at) DESC, created_at DESC LIMIT 1"

            target_cursor = connection.execute(query, tuple(params))
            target_row = target_cursor.fetchone()
            target = self._row_to_record(target_row) if target_row is not None else None

            now_iso = datetime.now(UTC).isoformat()
            if current is not None:
                connection.execute(
                    "UPDATE projection_manifests SET status = 'ROLLED_BACK' WHERE projection_id = ?",
                    (current.projection_id,),
                )

            if target is not None:
                connection.execute(
                    "UPDATE projection_manifests SET status = 'ACTIVE', activated_at = ? WHERE projection_id = ?",
                    (now_iso, target.projection_id),
                )

            # Retrieve updated state from the same connection
            demoted_record = None
            if current is not None:
                d_row = connection.execute(
                    """
                    SELECT projection_id, release_id, backend_id, status,
                           schema_version, model_version, input_digest, output_digest,
                           record_count, manifest_json, created_at, activated_at
                    FROM projection_manifests WHERE projection_id = ?
                    """,
                    (current.projection_id,),
                ).fetchone()
                demoted_record = self._row_to_record(d_row) if d_row else None

            restored_record = None
            if target is not None:
                r_row = connection.execute(
                    """
                    SELECT projection_id, release_id, backend_id, status,
                           schema_version, model_version, input_digest, output_digest,
                           record_count, manifest_json, created_at, activated_at
                    FROM projection_manifests WHERE projection_id = ?
                    """,
                    (target.projection_id,),
                ).fetchone()
                restored_record = self._row_to_record(r_row) if r_row else None

            return demoted_record, restored_record

    def reset(self) -> None:
        """Delete all projection manifest records (used in test isolation)."""
        with self._lock, self._session() as connection:
            connection.execute("DELETE FROM projection_manifests")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ProjectionManifestRecord:
        return ProjectionManifestRecord(
            projection_id=row["projection_id"],
            release_id=row["release_id"],
            backend_id=row["backend_id"],
            status=row["status"],
            schema_version=row["schema_version"],
            model_version=row["model_version"],
            input_digest=row["input_digest"],
            output_digest=row["output_digest"],
            record_count=int(row["record_count"]),
            manifest_json=row["manifest_json"],
            created_at=row["created_at"],
            activated_at=row["activated_at"],
        )
