"""Tests for Full Projection-Aware Rollback in the REST API."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from contracts.projections import ProjectionManifestRecord
from infrastructure.api import server as api_server
from infrastructure.api.server import create_server


@pytest.fixture(scope="module")
def server_url():
    """Start API server on ephemeral port for projection rollback testing."""
    api_server.GRAPH_STORE.reset()
    api_server.PROJECTION_STORE.reset()
    server, active_port = create_server("127.0.0.1", 8092)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{active_port}"
    server.shutdown()


def test_get_active_projections_initially_empty(server_url):
    """GET /api/projections/active returns empty list when no projections are active."""
    api_server.PROJECTION_STORE.reset()
    req = urllib.request.Request(f"{server_url}/api/projections/active")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["count"] == 0
        assert data["active_projections"] == []


def test_pipeline_execution_and_projection_rollback(server_url):
    """Verify that executing releases activates projections, and /api/release/rollback restores the prior projection."""
    api_server.GRAPH_STORE.reset()
    api_server.PROJECTION_STORE.reset()

    # 1. Execute first release (release_run_a)
    payload_a = json.dumps(
        {
            "pipeline_type": "e2e_release",
            "run_id": "run_a",
            "domain_pack": "synthetic",
        }
    ).encode("utf-8")
    req_a = urllib.request.Request(
        f"{server_url}/api/pipeline/execute",
        data=payload_a,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_a) as resp:
        assert resp.status == 200
        res_a = json.loads(resp.read().decode("utf-8"))
        assert res_a["status"] == "success"

    # Verify active projection for release_run_a
    req_active = urllib.request.Request(f"{server_url}/api/projections/active")
    with urllib.request.urlopen(req_active) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["count"] >= 1
        active_rec = data["active_projections"][0]
        assert active_rec["release_id"] == "release_run_a"
        assert active_rec["status"] == "ACTIVE"

    # 2. Execute second release (release_run_b)
    payload_b = json.dumps(
        {
            "pipeline_type": "e2e_release",
            "run_id": "run_b",
            "domain_pack": "synthetic",
        }
    ).encode("utf-8")
    req_b = urllib.request.Request(
        f"{server_url}/api/pipeline/execute",
        data=payload_b,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_b) as resp:
        assert resp.status == 200
        res_b = json.loads(resp.read().decode("utf-8"))
        assert res_b["status"] == "success"

    # Verify active projection switched to release_run_b
    with urllib.request.urlopen(req_active) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        active_rec = data["active_projections"][0]
        assert active_rec["release_id"] == "release_run_b"
        assert active_rec["status"] == "ACTIVE"

    # 3. Trigger /api/release/rollback
    req_rollback = urllib.request.Request(
        f"{server_url}/api/release/rollback",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_rollback) as resp:
        assert resp.status == 200
        rollback_data = json.loads(resp.read().decode("utf-8"))
        assert rollback_data["status"] == "success"
        rb = rollback_data["rollback"]
        assert rb["durability"] == "sqlite"
        assert len(rb["demoted_projections"]) >= 1
        assert len(rb["restored_projections"]) >= 1
        assert rb["active_release_id"] == "release_run_a"
        restored = rb["restored_projections"][0]
        assert restored["release_id"] == "release_run_a"
        assert restored["status"] == "ACTIVE"

    # 4. Verify GET /api/projections/active now reflects restored release_run_a
    with urllib.request.urlopen(req_active) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        active_rec = data["active_projections"][0]
        assert active_rec["release_id"] == "release_run_a"
        assert active_rec["status"] == "ACTIVE"


def test_rollback_with_target_release_id(server_url):
    """Verify rollback correctly targets a specified historical release."""
    api_server.PROJECTION_STORE.reset()

    # Seed three projection manifests (create release rows to satisfy FKs)
    for r_id in ("rel_v1", "rel_v2", "rel_v3"):
        if api_server.GRAPH_STORE.get_release(r_id) is None:
            api_server.GRAPH_STORE.save_release(
                r_id, {"type": "test", "created_at": "2026-01-01T00:00:00Z"}
            )

    api_server.PROJECTION_STORE.record_manifest(
        ProjectionManifestRecord(
            projection_id="proj_v1",
            release_id="rel_v1",
            backend_id="memory",
            status="ROLLED_BACK",
            schema_version="1.0.0",
            input_digest="hash1",
            output_digest="out1",
            record_count=10,
            created_at="2026-01-01T00:00:00Z",
            activated_at="2026-01-01T00:00:00Z",
        )
    )
    api_server.PROJECTION_STORE.record_manifest(
        ProjectionManifestRecord(
            projection_id="proj_v2",
            release_id="rel_v2",
            backend_id="memory",
            status="ROLLED_BACK",
            schema_version="1.0.0",
            input_digest="hash2",
            output_digest="out2",
            record_count=20,
            created_at="2026-01-02T00:00:00Z",
            activated_at="2026-01-02T00:00:00Z",
        )
    )
    api_server.PROJECTION_STORE.record_manifest(
        ProjectionManifestRecord(
            projection_id="proj_v3",
            release_id="rel_v3",
            backend_id="memory",
            status="ACTIVE",
            schema_version="1.0.0",
            input_digest="hash3",
            output_digest="out3",
            record_count=30,
            created_at="2026-01-03T00:00:00Z",
            activated_at="2026-01-03T00:00:00Z",
        )
    )

    # Roll back explicitly targeting rel_v1 (skipping v2)
    payload = json.dumps({"target_release_id": "rel_v1"}).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/release/rollback",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        rb = data["rollback"]
        assert rb["active_release_id"] == "rel_v1"
        assert any(p["projection_id"] == "proj_v1" for p in rb["restored_projections"])
        assert "proj_v3" in rb["demoted_projections"]

    # Verify store status
    p1 = api_server.PROJECTION_STORE.get("proj_v1")
    assert p1 is not None and p1.status == "ACTIVE"
    p3 = api_server.PROJECTION_STORE.get("proj_v3")
    assert p3 is not None and p3.status == "ROLLED_BACK"


def test_rollback_returns_409_when_no_history(server_url):
    """Verify HTTP 409 is returned when neither graph snapshots nor prior projections exist."""
    api_server.GRAPH_STORE.reset()
    api_server.PROJECTION_STORE.reset()

    req = urllib.request.Request(
        f"{server_url}/api/release/rollback",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 409
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body["status"] == "unavailable"
