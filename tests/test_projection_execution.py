"""Tests for Real Projection Execution (Phase 5 / Section 1 of plan.md).

Verifies:
1. Canonical ProjectionBackend protocol compliance.
2. MemoryProjectionBackend full lifecycle (build, validate, records, activate, rollback, destroy).
3. DurableProjectionStore SQLite CRUD, statuses, and query methods.
4. AuthoritativeReleaseRDFSource dynamic dataset compilation from AssertionStore.
5. Failure-injection on projection build/validation quarantining release and blocking endpoint switch.
6. Failure-injection on reconciliation blocking endpoint switch.
7. Projection manifest persistence across pipeline runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from contracts.projections import ProjectionBackend, ProjectionManifestRecord
from core.assertions.assertion import Assertion
from core.identifiers.identifier import Identifier
from core.projection.profile import ProjectionProfile, UnsupportedBehavior
from core.provenance.provenance import Provenance
from core.rdf.graph import RDFDataset
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource
from infrastructure.projections.memory import MemoryProjectionBackend, conforms_to_backend
from infrastructure.release.pipeline import EndToEndReleasePipeline
from infrastructure.storage.assertion_store import DurableAssertionStore
from infrastructure.storage.graph_store import GraphStore
from infrastructure.storage.projection_store import DurableProjectionStore
from plugins.synthetic import SyntheticDomainPack


def test_canonical_projection_contract_conformance():
    """Verify that backends implement the canonical ProjectionBackend protocol."""
    mem = MemoryProjectionBackend()
    assert isinstance(mem, ProjectionBackend)
    assert conforms_to_backend(mem)
    assert mem.backend_id == "memory"


def test_memory_projection_backend_lifecycle():
    """Verify MemoryProjectionBackend supports build, validate, records, activate, rollback, destroy."""
    mem = MemoryProjectionBackend()
    profile = ProjectionProfile(
        profile_id="test_profile",
        profile_version="1.0.0",
        unsupported_behavior=UnsupportedBehavior.SKIP,
    )

    build_res = mem.build("proj_1", "rel_1", profile)
    assert build_res.record_count == 0
    assert build_res.backend_id == "memory"

    val_res = mem.validate("proj_1")
    assert val_res.passed is True
    assert val_res.errors == ()

    assert mem.records("proj_1") == ()

    # Test activation and rollback
    mem.activate("proj_1")
    mem.rollback("proj_1")

    # Test destroy
    mem.destroy("proj_1")
    val_after = mem.validate("proj_1")
    assert val_after.passed is False


def test_durable_projection_store_crud(tmp_path: Path):
    """Verify SQLite persistence for projection manifests."""
    db_path = tmp_path / "projections.sqlite3"
    store = DurableProjectionStore(db_path)

    # Need a sentinel release in releases table for FK
    graph_store = GraphStore(db_path)
    graph_store.save_release("rel_001", {"nodes": [], "edges": []})

    manifest = ProjectionManifestRecord(
        projection_id="proj_001",
        release_id="rel_001",
        backend_id="memory",
        status="READY",
        schema_version="1.0.0",
        input_digest="inp_123",
        output_digest="out_456",
        record_count=42,
        manifest_json='{"test": true}',
        created_at=datetime.now(UTC).isoformat(),
    )

    store.record_manifest(manifest)

    # Retrieve
    loaded = store.get("proj_001")
    assert loaded is not None
    assert loaded.projection_id == "proj_001"
    assert loaded.release_id == "rel_001"
    assert loaded.record_count == 42
    assert loaded.status == "READY"

    # Update status
    now_iso = datetime.now(UTC).isoformat()
    store.update_status("proj_001", "ACTIVE", activated_at=now_iso)
    updated = store.get("proj_001")
    assert updated is not None
    assert updated.status == "ACTIVE"
    assert updated.activated_at == now_iso

    # Query active by backend
    active = store.get_active_by_backend("memory")
    assert active is not None
    assert active.projection_id == "proj_001"

    # Query by release
    by_rel = store.get_by_release("rel_001")
    assert len(by_rel) == 1
    assert by_rel[0].projection_id == "proj_001"


def test_authoritative_release_rdf_source_from_assertions(tmp_path: Path):
    """Verify AuthoritativeReleaseRDFSource constructs RDFDataset from persisted AssertionStore."""
    db_path = tmp_path / "assertions.sqlite3"
    graph_store = GraphStore(db_path)
    graph_store.save_release("rel_test", {"nodes": [], "edges": []})

    assertion_store = DurableAssertionStore(db_path)
    aid = Identifier(namespace="ASN", value="asn_99")
    assertion = Assertion(
        id=aid,
        subject=Identifier(namespace="ENT", value="subj_1"),
        predicate="urn:test:predicate",
        object=Identifier(namespace="ENT", value="obj_1"),
        provenance=Provenance(
            agent_id=Identifier(namespace="AGT", value="agent_1"),
            activity_id=Identifier(namespace="ACT", value="act_1"),
            asserted_at=datetime.now(UTC),
        ),
    )
    assertion_store.persist_batch([assertion], [])
    assertion_store.link_release_assertions("rel_test", [aid.canonical])

    source = AuthoritativeReleaseRDFSource(assertion_store=assertion_store)
    ds = source.get("rel_test")

    assert ds is not None
    assert isinstance(ds, RDFDataset)
    assert len(ds.graphs) > 0


def test_pipeline_failure_injection_projection_stage():
    """Verify injected projection failure marks stage FAIL and blocks endpoint switch."""
    pipeline = EndToEndReleasePipeline()
    pack = SyntheticDomainPack()

    result = pipeline.execute_pipeline(
        plugin_pack=pack,
        run_id="fail_proj_001",
        injected_failure_stage="projection",
    )

    assert result.stage_statuses["projection"] == "FAIL"
    assert result.stage_statuses["endpoint_switch"] == "FAIL"
    assert result.switched_endpoint is False


def test_pipeline_failure_injection_reconciliation_stage():
    """Verify injected reconciliation failure marks stage FAIL and blocks endpoint switch."""
    pipeline = EndToEndReleasePipeline()
    pack = SyntheticDomainPack()

    result = pipeline.execute_pipeline(
        plugin_pack=pack,
        run_id="fail_rec_001",
        injected_failure_stage="reconciliation",
    )

    assert result.stage_statuses["reconciliation"] == "FAIL"
    assert result.stage_statuses["endpoint_switch"] == "FAIL"
    assert result.switched_endpoint is False
    assert result.reconciled is False


def test_pipeline_persists_projection_manifests(tmp_path: Path):
    """Verify that running the pipeline records projection manifests into DurableProjectionStore."""
    db_path = tmp_path / "pipeline.sqlite3"
    graph_store = GraphStore(db_path)
    run_id = "run_manifest_001"
    release_id = f"release_{run_id}"
    graph_store.save_release(release_id, {"nodes": [], "edges": []})

    projection_store = DurableProjectionStore(db_path)
    pipeline = EndToEndReleasePipeline(projection_store=projection_store)
    pack = SyntheticDomainPack()

    result = pipeline.execute_pipeline(plugin_pack=pack, run_id=run_id)

    assert result.stage_statuses["projection"] == "PASS"
    assert result.stage_statuses["reconciliation"] == "PASS"
    assert result.stage_statuses["endpoint_switch"] == "PASS"
    assert result.stage_statuses["rollback"] == "PASS"

    manifests = projection_store.get_by_release(release_id)
    assert len(manifests) == 1
    proj_manifest = manifests[0]
    assert proj_manifest.release_id == release_id
    assert proj_manifest.backend_id == "memory"
    # Stage 13 verified rollback on canary without de-activating production projection
    assert proj_manifest.status == "ACTIVE"
    assert proj_manifest.output_digest != ""
