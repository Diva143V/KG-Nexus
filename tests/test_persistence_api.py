"""Tests for Artifact, Assertion, and Backup API endpoints."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from core.resources.artifact import ArtifactKind
from infrastructure.api import server as api_server
from infrastructure.api.server import create_server


@pytest.fixture(scope="module")
def api_url(tmp_path_factory):
    test_db = tmp_path_factory.mktemp("api_storage") / "test_api.sqlite3"
    # Switch server stores to isolated test DB
    from infrastructure.storage import DurableArtifactStore, DurableAssertionStore, GraphStore

    api_server.GRAPH_STORE = GraphStore(test_db)
    api_server.ARTIFACT_STORE = DurableArtifactStore(test_db)
    api_server.ASSERTION_STORE = DurableAssertionStore(test_db)

    server, active_port = create_server("127.0.0.1", 8190)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{active_port}"
    server.shutdown()


def test_api_artifact_endpoints(api_url):
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
    rel_id = Identifier(namespace="release", value="rel-api-1")
    api_server.GRAPH_STORE.save_release(rel_id.value, {"nodes": [], "edges": []})

    # Ingest artifact
    artifact = api_server.ARTIFACT_STORE.store(
        content=b"Sample payload data for API test",
        source_release_id=rel_id,
        media_type="text/plain",
        name="sample.txt",
        kind=ArtifactKind.DOCUMENT,
        retrieved_at=now,
    )

    # 1. GET metadata
    req = urllib.request.Request(f"{api_url}/api/artifacts/{artifact.id.canonical}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["artifact"]["id"]["value"] == artifact.id.value
        assert data["artifact"]["sha256"] == artifact.sha256

    # 2. GET verify integrity (Pass)
    req_v = urllib.request.Request(f"{api_url}/api/artifacts/{artifact.id.canonical}/verify")
    with urllib.request.urlopen(req_v) as resp:
        assert resp.status == 200
        data_v = json.loads(resp.read().decode("utf-8"))
        assert data_v["status"] == "ok"

    # 3. Corrupt BLOB and verify integrity (Fail)
    con = sqlite3.connect(api_server.GRAPH_STORE.database_path)
    con.execute(
        "UPDATE artifacts SET content = ? WHERE id = ?",
        (sqlite3.Binary(b"Corrupted BLOB content"), artifact.id.canonical),
    )
    con.commit()
    con.close()

    req_v_fail = urllib.request.Request(f"{api_url}/api/artifacts/{artifact.id.canonical}/verify")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_v_fail)
    assert exc_info.value.code == 409
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert err_body["status"] == "fail"
    assert err_body["error"] == "digest mismatch"


def test_api_artifact_not_found(api_url):
    req = urllib.request.Request(f"{api_url}/api/artifacts/artifact:nonexistent_sha_code")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 404


def test_api_assertion_endpoints(api_url):
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-api"),
        activity_id=Identifier(namespace="activity", value="act-api"),
        asserted_at=now,
    )
    assertion = Assertion(
        id=Identifier(namespace="assertion", value="ass-api-1"),
        subject=Identifier(namespace="gene", value="BRCA1"),
        predicate="associated_with",
        object=Identifier(namespace="disease", value="Breast_Cancer"),
        status_at_creation=AssertionState.CANDIDATE,
        confidence=Confidence(score=0.9, method=ConfidenceMethod.STATISTICAL),
        provenance=prov,
    )
    event = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-api-1"),
        assertion_id=assertion.id,
        from_state=AssertionState.CANDIDATE,
        to_state=AssertionState.VERIFIED,
        agent_id=Identifier(namespace="agent", value="curator-api"),
        activity_id=Identifier(namespace="activity", value="act-api"),
        policy_version="1.0.0",
        reason_code="VERIFIED_BY_LITERATURE",
        timestamp=now,
    )

    api_server.ASSERTION_STORE.persist_batch([assertion], [event])

    req = urllib.request.Request(f"{api_url}/api/assertions/{assertion.id.canonical}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["assertion"]["id"]["value"] == "ass-api-1"
        assert data["current_state"] == "verified"
        assert len(data["events"]) == 1
        assert data["events"][0]["reason_code"] == "VERIFIED_BY_LITERATURE"


def test_api_backup_endpoint(api_url, tmp_path):
    backup_target_dir = tmp_path / "api_backups"
    payload = json.dumps({"backup_dir": str(backup_target_dir)}).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url}/api/backup",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["verified"] is True
        backup_file = Path(data["backup_path"])
        assert backup_file.exists()
