"""Durable storage for the currently active graph and rollback snapshots."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime  # FIX CRITICAL-1a: added 'datetime' (was only UTC)
from pathlib import Path
from typing import Any, cast

from infrastructure.storage.migration_runner import MigrationRunner


class GraphStore:
    """SQLite-backed graph store with atomic replacement and rollback support."""

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
            yield connection
        finally:
            connection.close()

    def checkpoint(self) -> None:
        with self._lock, self._session() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def save_release(
        self,
        release_id: str,
        payload: dict[str, Any],
        *,
        artifact_ids: list[str] | None = None,
        assertion_ids: list[str] | None = None,
        fusion_run: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist an immutable serialized fusion result by release ID.

        Optionally validates artifact_ids and assertion_ids existence, and persists
        fusion_run and release_assertions associations atomically with the release row.
        """
        payload_json = json.dumps(payload, sort_keys=True)
        with self._lock, self._session() as connection:
            # Capstone validation: ensure all referenced artifacts and assertions exist
            if artifact_ids:
                for art_id in artifact_ids:
                    row = connection.execute(
                        "SELECT 1 FROM artifacts WHERE id = ? OR sha256 = ?", (art_id, art_id)
                    ).fetchone()
                    if row is None:
                        raise ValueError(f"Referenced artifact not found: {art_id}")

            if assertion_ids:
                for ass_id in assertion_ids:
                    row = connection.execute(
                        "SELECT 1 FROM assertions WHERE id = ?", (ass_id,)
                    ).fetchone()
                    if row is None:
                        raise ValueError(f"Referenced assertion not found: {ass_id}")

            existing = connection.execute(
                "SELECT payload_json FROM releases WHERE release_id = ?",
                (release_id,),
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(existing["payload_json"])
                existing_run = existing_payload.get("fusion_run", {})
                requested_run = payload.get("fusion_run", {})
                identity_fields = (
                    "fusion_run_id",
                    "graph_a_release_id",
                    "graph_b_release_id",
                    "domain_id",
                    "conflict_mode",
                )
                if any(
                    existing_run.get(field) != requested_run.get(field) for field in identity_fields
                ):
                    raise ValueError(f"immutable release ID collision: {release_id}")
                return cast(dict[str, Any], existing_payload)

            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO releases (release_id, payload_json) VALUES (?, ?)",
                (release_id, payload_json),
            )
            if assertion_ids:
                for ass_id in assertion_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO release_assertions (release_id, assertion_id) VALUES (?, ?)",
                        (release_id, ass_id),
                    )

            if fusion_run is not None:
                config_json = json.dumps(fusion_run.get("config", {}), sort_keys=True)
                config_digest = str(fusion_run.get("config_digest", ""))
                policy_digest = str(fusion_run.get("policy_digest", ""))
                engine_version = str(fusion_run.get("engine_version", "1.0.0"))
                input_artifacts = json.dumps(artifact_ids or [])
                output_digest = str(fusion_run.get("output_digest", ""))
                conflicts_json = json.dumps(fusion_run.get("conflicts", []))
                audit_json = json.dumps(fusion_run.get("audit", []))
                connection.execute(
                    """
                    INSERT INTO fusion_runs (
                        release_id, config_json, config_digest, policy_digest,
                        engine_version, input_artifact_ids, output_digest,
                        conflicts_json, audit_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        config_json,
                        config_digest,
                        policy_digest,
                        engine_version,
                        input_artifacts,
                        output_digest,
                        conflicts_json,
                        audit_json,
                    ),
                )
            connection.commit()
            return payload

    def get_release(self, release_id: str) -> dict[str, Any] | None:
        """Load a persisted fusion result by release ID."""
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT payload_json FROM releases WHERE release_id = ?",
                (release_id,),
            ).fetchone()
            if row is None:
                return None
            payload = cast(dict[str, Any], json.loads(row["payload_json"]))

            # Overlay latest status from release_status_history if present
            try:
                status_row = connection.execute(
                    "SELECT status, quarantine_reasons FROM release_status_history WHERE release_id = ? ORDER BY id DESC LIMIT 1",
                    (release_id,),
                ).fetchone()
                if status_row is not None:
                    payload["status"] = status_row["status"]
                    if status_row["quarantine_reasons"]:
                        try:
                            payload["quarantine_reasons"] = json.loads(
                                status_row["quarantine_reasons"]
                            )
                        except Exception:
                            payload["quarantine_reasons"] = status_row["quarantine_reasons"]
            except Exception:
                pass

            # Overlay latest lifecycle from release_lifecycle if present
            try:
                lc_row = connection.execute(
                    "SELECT lifecycle_json FROM release_lifecycle WHERE release_id = ? ORDER BY id DESC LIMIT 1",
                    (release_id,),
                ).fetchone()
                if lc_row is not None:
                    payload["lifecycle"] = json.loads(lc_row["lifecycle_json"])
            except Exception:
                pass

            return payload

    # FIX CRITICAL-1b: save_release_lifecycle was previously defined at module level
    # (zero indentation) and thus was NOT a class method. Fixed by re-indenting it
    # into the class body (4-space indent for the def, 8-space for the body).
    def save_release_lifecycle(self, release_id: str, lifecycle: dict[str, Any]) -> None:
        """Attach an immutable lifecycle record to an existing release payload.

        Stores lifecycle changes in a separate versioned table rather than mutating
        the main releases.payload_json, preserving immutability of release records.
        """
        lifecycle_json = json.dumps(lifecycle, sort_keys=True)
        with self._lock, self._session() as connection:
            # Check if release exists
            row = connection.execute(
                "SELECT payload_json FROM releases WHERE release_id = ?",
                (release_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown release: {release_id}")

            # Store lifecycle in separate versioned table
            existing_lifecycle = connection.execute(
                "SELECT lifecycle_json, created_at FROM release_lifecycle "
                "WHERE release_id = ? ORDER BY created_at DESC LIMIT 1",
                (release_id,),
            ).fetchone()

            # FIX HIGH-3: guard was `== lifecycle_json` (raised on idempotent write,
            # allowed actual mutations). Corrected to `!=` — raise only when content
            # differs; silently accept idempotent re-writes.
            if existing_lifecycle is not None:
                prev_lifecycle = json.loads(existing_lifecycle[0])
                if json.dumps(prev_lifecycle, sort_keys=True) != lifecycle_json:
                    raise ValueError(f"immutable lifecycle collision: {release_id}")
                return  # idempotent — same content already persisted

            connection.execute(
                "INSERT INTO release_lifecycle (release_id, lifecycle_json, created_at) VALUES (?, ?, ?)",
                (release_id, lifecycle_json, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def update_release_status(
        self,
        release_id: str,
        status: str,
        *,
        quarantine_reasons: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """Update the status (and optional quarantine reasons) of an existing release.

        Stores status changes in a separate versioned table rather than mutating
        the main releases.payload_json, preserving immutability of release records.
        """
        with self._lock, self._session() as connection:
            # Check if release exists
            row = connection.execute(
                "SELECT payload_json FROM releases WHERE release_id = ?",
                (release_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown release: {release_id}")

            # FIX MEDIUM-3: quarantine_reasons must be JSON-serialized. Previously
            # it was passed as a raw Python list/tuple, which SQLite stores as
            # Python repr() — not valid JSON and undeserializable without ast.literal_eval.
            quarantine_json = json.dumps(list(quarantine_reasons)) if quarantine_reasons else None

            # Store status change in separate versioned table
            connection.execute(
                "INSERT INTO release_status_history (release_id, status, quarantine_reasons, changed_at) VALUES (?, ?, ?, ?)",
                (release_id, status, quarantine_json, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def get_active(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT nodes_json, edges_json FROM active_graph WHERE id = 1"
            ).fetchone()
            if row is None:
                return {"nodes": [], "edges": []}
            return {
                "nodes": json.loads(row["nodes_json"]),
                "edges": json.loads(row["edges_json"]),
            }

    def replace_active(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> None:
        nodes_json = json.dumps(nodes, sort_keys=True)
        edges_json = json.dumps(edges, sort_keys=True)
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT nodes_json, edges_json FROM active_graph WHERE id = 1"
            ).fetchone()
            if current is not None:
                connection.execute(
                    "INSERT INTO graph_snapshots (nodes_json, edges_json) VALUES (?, ?)",
                    (current["nodes_json"], current["edges_json"]),
                )
            connection.execute(
                """
                INSERT INTO active_graph (id, nodes_json, edges_json) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nodes_json = excluded.nodes_json,
                    edges_json = excluded.edges_json
                """,
                (nodes_json, edges_json),
            )
            connection.commit()

    def rollback(self) -> dict[str, list[dict[str, Any]]] | None:
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = connection.execute(
                """
                SELECT snapshot_id, nodes_json, edges_json
                FROM graph_snapshots
                ORDER BY snapshot_id DESC LIMIT 1
                """
            ).fetchone()
            if snapshot is None:
                connection.rollback()
                return None
            current = connection.execute(
                "SELECT nodes_json, edges_json FROM active_graph WHERE id = 1"
            ).fetchone()
            if current is not None:
                connection.execute(
                    "INSERT INTO graph_snapshots (nodes_json, edges_json) VALUES (?, ?)",
                    (current["nodes_json"], current["edges_json"]),
                )
            connection.execute(
                "UPDATE active_graph SET nodes_json = ?, edges_json = ? WHERE id = 1",
                (snapshot["nodes_json"], snapshot["edges_json"]),
            )
            connection.execute(
                "DELETE FROM graph_snapshots WHERE snapshot_id = ?",
                (snapshot["snapshot_id"],),
            )
            connection.commit()
            return {
                "nodes": json.loads(snapshot["nodes_json"]),
                "edges": json.loads(snapshot["edges_json"]),
            }

    def get_release_assertions(self, release_id: str) -> list[str]:
        with self._lock, self._session() as connection:
            rows = connection.execute(
                "SELECT assertion_id FROM release_assertions WHERE release_id = ? ORDER BY assertion_id ASC",
                (release_id,),
            ).fetchall()
            return [str(row["assertion_id"]) for row in rows]

    def get_fusion_run(self, release_id: str) -> dict[str, Any] | None:
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT * FROM fusion_runs WHERE release_id = ?",
                (release_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "release_id": row["release_id"],
                "config": json.loads(row["config_json"]),
                "config_digest": row["config_digest"],
                "policy_digest": row["policy_digest"],
                "engine_version": row["engine_version"],
                "input_artifact_ids": json.loads(row["input_artifact_ids"]),
                "output_digest": row["output_digest"],
                "conflicts": json.loads(row["conflicts_json"]),
                "audit": json.loads(row["audit_json"]),
                "created_at": row["created_at"],
            }

    def reset(self) -> None:
        """Clear active data and snapshots for isolated test or development runs."""
        with self._lock, self._session() as connection:
            connection.execute("DELETE FROM projection_manifests")
            connection.execute("DELETE FROM artifacts")
            connection.execute("DELETE FROM release_assertions")
            connection.execute("DELETE FROM assertion_state_events")
            connection.execute("DELETE FROM assertions")
            connection.execute("DELETE FROM fusion_runs")
            connection.execute("DELETE FROM graph_snapshots")
            connection.execute("DELETE FROM releases")
            connection.execute(
                "UPDATE active_graph SET nodes_json = '[]', edges_json = '[]' WHERE id = 1"
            )
            connection.commit()
