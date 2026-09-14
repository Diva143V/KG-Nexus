"""Tests for Full End-to-End Release Pipeline (Phase 25)."""

from infrastructure.release.pipeline import EndToEndReleasePipeline
from plugins.biomedical import BiomedicalDomainPack
from plugins.synthetic import SyntheticDomainPack


def test_end_to_end_pipeline_synthetic_plugin():
    pipeline = EndToEndReleasePipeline()
    pack = SyntheticDomainPack()

    result = pipeline.execute_pipeline(plugin_pack=pack, run_id="run_synth_001")

    assert result.manifest.plugin_id == "synthetic_domain_pack"
    assert result.stage_statuses["ingest"] == "PASS"
    assert result.stage_statuses["endpoint_switch"] == "PASS"
    assert result.reconciled is True
    assert result.switched_endpoint is True
    assert result.rollback_successful is True


def test_end_to_end_pipeline_biomedical_plugin():
    pipeline = EndToEndReleasePipeline()
    pack = BiomedicalDomainPack()

    result = pipeline.execute_pipeline(plugin_pack=pack, run_id="run_bio_001")

    assert result.manifest.plugin_id == "biomedical_domain_pack"
    assert result.stage_statuses["validation"] == "PASS"
    assert result.stage_statuses["rdf_snapshot"] == "PASS"
    assert result.reconciled is True
    assert result.switched_endpoint is True
    assert result.rollback_successful is True
