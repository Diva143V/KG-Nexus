"""Durable, SQLite-backed assertion and state event storage."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.evidence.evidence import Evidence
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from infrastructure.storage.migration_runner import MigrationRunner


class DurableAssertionStore:
    """Durable SQLite-backed store for assertions and append-only state transition events."""

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

    def _prepare_provenance_json(self, provenance: Provenance) -> str:
        """Serialise provenance, ensuring source_artifact_id always carries the
        full canonical namespace prefix (e.g. ``artifact:<sha256>``).
        This guarantees the generated SQL column is unambiguous for index lookups.
        """
        prov = provenance
        # Back-fill source_artifact_id from input_resource_refs if absent.
        if prov.source_artifact_id is None and prov.input_resource_refs:
            for ref in prov.input_resource_refs:
                if ref.namespace == "artifact":
                    prov = prov.model_copy(update={"source_artifact_id": ref.canonical})
                    break
        # Enforce canonical prefix: if stored without namespace, add it.
        if prov.source_artifact_id is not None and ":" not in prov.source_artifact_id:
            prov = prov.model_copy(
                update={"source_artifact_id": f"artifact:{prov.source_artifact_id}"}
            )
        return prov.model_dump_json()

    def _insert_assertion(self, connection: sqlite3.Connection, assertion: Assertion) -> None:
        evidence_json = json.dumps(
            [e.model_dump(mode="json") for e in assertion.evidence], sort_keys=True
        )
        prov_json = self._prepare_provenance_json(assertion.provenance)
        ctx_json = assertion.context.model_dump_json() if assertion.context else None
        conf_val = assertion.confidence.score if assertion.confidence else None
        conf_method = assertion.confidence.method.value if assertion.confidence else None

        connection.execute(
            """
            INSERT INTO assertions (
                id, subject_id, predicate, object_id, status_at_creation,
                confidence_value, confidence_method, evidence_json,
                provenance_json, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                assertion.id.canonical,
                assertion.subject.canonical,
                assertion.predicate,
                assertion.object.canonical,
                assertion.status_at_creation.value,
                conf_val,
                conf_method,
                evidence_json,
                prov_json,
                ctx_json,
            ),
        )

    def _insert_event(self, connection: sqlite3.Connection, event: AssertionStateEvent) -> None:
        from_st = event.from_state.value if event.from_state else None
        connection.execute(
            """
            INSERT INTO assertion_state_events (
                event_id, assertion_id, from_state, to_state,
                agent_id, activity_id, policy_version, reason_code, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event.event_id.canonical,
                event.assertion_id.canonical,
                from_st,
                event.to_state.value,
                event.agent_id.canonical,
                event.activity_id.canonical,
                event.policy_version,
                event.reason_code,
                event.timestamp.isoformat(),
            ),
        )

    def _row_to_assertion(self, row: sqlite3.Row) -> Assertion:
        conf = None
        if row["confidence_value"] is not None:
            method_str = row["confidence_method"] or ConfidenceMethod.UNSPECIFIED.value
            conf = Confidence(
                score=float(row["confidence_value"]), method=ConfidenceMethod(method_str)
            )

        # pyrefly: ignore [implicit-any-empty-container]
        evidence_list = []
        if row["evidence_json"]:
            ev_data = json.loads(row["evidence_json"])
            evidence_list = [Evidence.model_validate(e) for e in ev_data]

        prov = Provenance.model_validate_json(row["provenance_json"])
        ctx = Context.model_validate_json(row["context_json"]) if row["context_json"] else None

        return Assertion(
            id=Identifier.parse(row["id"]),
            subject=Identifier.parse(row["subject_id"]),
            predicate=row["predicate"],
            object=Identifier.parse(row["object_id"]),
            status_at_creation=AssertionState(row["status_at_creation"]),
            confidence=conf,
            evidence=tuple(evidence_list),
            provenance=prov,
            context=ctx,
        )

    def _row_to_event(self, row: sqlite3.Row) -> AssertionStateEvent:
        from_st = AssertionState(row["from_state"]) if row["from_state"] else None
        return AssertionStateEvent(
            event_id=Identifier.parse(row["event_id"]),
            assertion_id=Identifier.parse(row["assertion_id"]),
            from_state=from_st,
            to_state=AssertionState(row["to_state"]),
            agent_id=Identifier.parse(row["agent_id"]),
            activity_id=Identifier.parse(row["activity_id"]),
            policy_version=row["policy_version"],
            reason_code=row["reason_code"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    def persist_assertion(self, assertion: Assertion) -> None:
        """Persist a single assertion."""
        with self._lock, self._session() as connection:
            self._insert_assertion(connection, assertion)
            connection.commit()

    def persist_state_event(self, event: AssertionStateEvent) -> None:
        """Persist an append-only state event."""
        with self._lock, self._session() as connection:
            self._insert_event(connection, event)
            connection.commit()

    def persist_batch(self, assertions: list[Assertion], events: list[AssertionStateEvent]) -> None:
        """Persist multiple assertions and events in a single atomic transaction."""
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for assertion in assertions:
                    self._insert_assertion(connection, assertion)
                for event in events:
                    self._insert_event(connection, event)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_assertion(self, assertion_id: Identifier | str) -> Assertion | None:
        """Load an assertion by identifier."""
        canonical_id = (
            assertion_id.canonical if isinstance(assertion_id, Identifier) else assertion_id
        )
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT * FROM assertions WHERE id = ?",
                (canonical_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_assertion(row)

    def get_state_events(self, assertion_id: Identifier | str) -> list[AssertionStateEvent]:
        """Load all state events for an assertion in temporal order."""
        canonical_id = (
            assertion_id.canonical if isinstance(assertion_id, Identifier) else assertion_id
        )
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM assertion_state_events
                WHERE assertion_id = ?
                ORDER BY timestamp ASC, created_at ASC
                """,
                (canonical_id,),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def get_by_source_artifact(self, artifact_id: Identifier | str) -> list[Assertion]:
        """Query assertions originating from a specific source artifact via indexed generated column.

        ``source_artifact_id`` is always stored with the full ``artifact:<value>`` prefix,
        so this method normalises the caller's input before querying.
        """
        if isinstance(artifact_id, Identifier):
            canonical_id = artifact_id.canonical  # already "artifact:<value>"
        else:
            canonical_id = artifact_id if ":" in artifact_id else f"artifact:{artifact_id}"
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM assertions
                WHERE source_artifact_id = ?
                ORDER BY created_at ASC
                """,
                (canonical_id,),
            ).fetchall()
            return [self._row_to_assertion(r) for r in rows]

    def get_by_graph_origin(self, graph_origin_id: str) -> list[Assertion]:
        """Query assertions originating from a specific graph origin ID."""
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM assertions
                WHERE graph_origin_id = ?
                ORDER BY created_at ASC
                """,
                (graph_origin_id,),
            ).fetchall()
            return [self._row_to_assertion(r) for r in rows]

    def link_release_assertions(self, release_id: str, assertion_ids: list[str]) -> None:
        """Link assertions to a release in release_assertions join table."""
        with self._lock, self._session() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO release_assertions (release_id, assertion_id)
                VALUES (?, ?)
                """,
                [(release_id, aid) for aid in assertion_ids],
            )

    def get_by_release(self, release_id: str) -> list[Assertion]:
        """Fetch all assertions associated with a release_id."""
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """
                SELECT a.* FROM assertions a
                JOIN release_assertions ra ON a.id = ra.assertion_id
                WHERE ra.release_id = ?
                ORDER BY a.created_at ASC
                """,
                (release_id,),
            ).fetchall()
            return [self._row_to_assertion(r) for r in rows]
