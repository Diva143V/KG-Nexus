"""Tests for Full 13-Stage Release Pipeline Activation with Durable Persistence and Formal Lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.assertions.state import AssertionState
from core.releases.status import ReleaseStatus
from infrastructure.release.pipeline import EndToEndReleasePipeline
from infrastructure.storage.artifact_store import DurableArtifactStore
from infrastructure.storage.assertion_store import DurableAssertionStore
from infrastructure.storage.graph_store import GraphStore
from infrastructure.storage.projection_store import DurableProjectionStore
from plugins.biomedical import BiomedicalDomainPack
from plugins.synthetic import SyntheticDomainPack


def test_13_stage_pipeline_full_execution_synthetic(tmp_path: Path):
    """Verify that all 13 stages execute real services, persist data, and publish for SyntheticDomainPack."""
    db_path = tmp_path / "synthetic_pipeline.sqlite3"
    graph_store = GraphStore(db_path)
    artifact_store = DurableArtifactStore(db_path)
    assertion_store = DurableAssertionStore(db_path)
    projection_store = DurableProjectionStore(db_path)

    pipeline = EndToEndReleasePipeline(
        database_path=db_path,
        graph_store=graph_store,
        artifact_store=artifact_store,
        assertion_store=assertion_store,
        projection_store=projection_store,
    )
    pack = SyntheticDomainPack()
    run_id = "synth_full_001"
    release_id = f"release_{run_id}"

    result = pipeline.execute_pipeline(plugin_pack=pack, run_id=run_id)

    # 1. All 13 stages must report PASS
    expected_stages = [
        "ingest",
        "normalize",
        "candidate_generation",
        "assertion_creation",
        "state_transitions",
        "provenance",
        "validation",
        "release",
        "rdf_snapshot",
        "projection",
        "reconciliation",
        "endpoint_switch",
        "rollback",
    ]
    for stage in expected_stages:
        assert result.stage_statuses.get(stage) == "PASS", (
            f"Stage {stage} did not PASS: {result.stage_statuses}"
        )

    assert result.reconciled is True
    assert result.switched_endpoint is True
    assert result.rollback_successful is True

    # 2. Stage evidence and timings recorded
    assert len(result.stage_evidence) == 13
    assert len(result.stage_timings_ms) == 13
    for stage in expected_stages:
        assert stage in result.stage_timings_ms

    # 3. ArtifactStore contains materialized ontology artifact
    artifacts = list(artifact_store.iter_artifacts())
    assert len(artifacts) >= 1
    assert any("synthetic_domain_pack" in (a.name or "") for a in artifacts)

    # 4. AssertionStore contains persisted assertions and state events
    release_assertions = assertion_store.get_by_release(release_id)
    assert len(release_assertions) >= 1
    sample_asn = next(
        (a for a in release_assertions if a.predicate == "urn:synthetic:located_in"), None
    )
    assert sample_asn is not None
    assert sample_asn.subject.namespace == "SYNTH"
    assert sample_asn.predicate == "urn:synthetic:located_in"

    events = assertion_store.get_state_events(sample_asn.id)
    assert len(events) >= 2
    assert any(e.to_state == AssertionState.CANDIDATE for e in events)
    assert any(e.to_state == AssertionState.VERIFIED for e in events)

    # 5. GraphStore release record is PUBLISHED
    rel_rec = graph_store.get_release(release_id)
    assert rel_rec is not None
    assert rel_rec["status"] == ReleaseStatus.PUBLISHED.value

    # 6. ProjectionStore record is ACTIVE (not demoted)
    proj_recs = projection_store.get_by_release(release_id)
    assert len(proj_recs) == 1
    assert proj_recs[0].status == "ACTIVE"


def test_13_stage_pipeline_full_execution_biomedical(tmp_path: Path):
    """Verify that all 13 stages execute real services, persist data, and publish for BiomedicalDomainPack."""
    db_path = tmp_path / "biomedical_pipeline.sqlite3"
    pipeline = EndToEndReleasePipeline(database_path=db_path)
    pack = BiomedicalDomainPack()
    run_id = "bio_full_001"
    release_id = f"release_{run_id}"

    result = pipeline.execute_pipeline(plugin_pack=pack, run_id=run_id)

    assert result.manifest.plugin_id == "biomedical_domain_pack"
    assert all(status == "PASS" for status in result.stage_statuses.values())
    assert result.reconciled is True
    assert result.switched_endpoint is True
    assert result.rollback_successful is True

    # Assertions linked and typed
    assertions = pipeline.assertion_store.get_by_release(release_id)
    assert len(assertions) >= 1
    bio_sample = next(
        (
            a
            for a in assertions
            if a.subject.namespace == "CHEMBL" and a.object.namespace == "UNIPROT"
        ),
        None,
    )
    assert bio_sample is not None
    assert bio_sample.subject.namespace == "CHEMBL"
    assert bio_sample.object.namespace == "UNIPROT"

    # Status in GraphStore is PUBLISHED
    rel = pipeline.graph_store.get_release(release_id)
    assert rel is not None
    assert rel["status"] == ReleaseStatus.PUBLISHED.value


def test_13_stage_pipeline_raw_artifact_ingestion(tmp_path: Path):
    """Verify custom raw artifacts provided to execute_pipeline are ingested and content-addressed."""
    db_path = tmp_path / "raw_pipeline.sqlite3"
    pipeline = EndToEndReleasePipeline(database_path=db_path)
    pack = SyntheticDomainPack()
    run_id = "raw_run_001"
    release_id = f"release_{run_id}"

    custom_content = b'{"source": "raw_test", "count": 100}'
    raw_artifacts = [
        {
            "name": "custom_data.json",
            "content": custom_content,
            "media_type": "application/json",
        }
    ]

    result = pipeline.execute_pipeline(
        plugin_pack=pack,
        run_id=run_id,
        raw_artifacts=raw_artifacts,
    )

    assert result.stage_statuses["ingest"] == "PASS"
    artifacts = list(pipeline.artifact_store.iter_artifacts())
    assert any(a.name == "custom_data.json" for a in artifacts)
    stored_raw = next(a for a in artifacts if a.name == "custom_data.json")
    assert pipeline.artifact_store.get_content(stored_raw.id) == custom_content
    assert stored_raw.source_release_id is not None
    assert stored_raw.source_release_id.value == release_id


@pytest.mark.parametrize(
    "fail_stage",
    [
        "ingest",
        "normalize",
        "candidate_generation",
        "assertion_creation",
        "state_transitions",
        "provenance",
        "validation",
        "release",
        "rdf_snapshot",
        "projection",
        "reconciliation",
        "endpoint_switch",
    ],
)
def test_pipeline_failure_injection_quarantines_release(tmp_path: Path, fail_stage: str):
    """Verify injected failure in any stage marks that stage FAIL, prevents endpoint switch, and quarantines release."""
    db_path = tmp_path / f"fail_{fail_stage}.sqlite3"
    pipeline = EndToEndReleasePipeline(database_path=db_path)
    pack = SyntheticDomainPack()
    run_id = f"fail_{fail_stage}_run"
    release_id = f"release_{run_id}"

    result = pipeline.execute_pipeline(
        plugin_pack=pack,
        run_id=run_id,
        injected_failure_stage=fail_stage,
    )

    assert result.stage_statuses[fail_stage] == "FAIL"
    assert result.stage_statuses["endpoint_switch"] == "FAIL"
    assert result.switched_endpoint is False

    # Check that release was quarantined in GraphStore
    rel_rec = pipeline.graph_store.get_release(release_id)
    assert rel_rec is not None
    assert rel_rec["status"] == ReleaseStatus.QUARANTINED.value


def test_pipeline_fail_closed_when_artifacts_produce_no_assertions(tmp_path: Path):
    """Verify Stage 4 fails closed honestly rather than hallucinating fake assertions."""
    db_path = tmp_path / "fail_closed.sqlite3"
    pipeline = EndToEndReleasePipeline(database_path=db_path)
    pack = SyntheticDomainPack()
    run_id = "fail_closed_001"
    release_id = f"release_{run_id}"

    empty_raw = [
        {
            "name": "empty.ttl",
            "content": b"# Just comments\n",
            "media_type": "turtle",
        }
    ]

    result = pipeline.execute_pipeline(
        plugin_pack=pack,
        run_id=run_id,
        raw_artifacts=empty_raw,
    )

    assert result.stage_statuses["assertion_creation"] == "FAIL"
    assert "No assertions could be parsed" in result.stage_evidence["assertion_creation"]["error"]
    assert result.stage_statuses["endpoint_switch"] == "FAIL"
    assert result.switched_endpoint is False

    rel_rec = pipeline.graph_store.get_release(release_id)
    assert rel_rec is not None
    assert rel_rec["status"] == ReleaseStatus.QUARANTINED.value
