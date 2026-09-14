"""Tests for Biomedical Source Adapters (Phase 17)."""

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters import (
    ChEBISourceAdapter,
    ChEMBLSourceAdapter,
    EnsemblSourceAdapter,
    HGNCSourceAdapter,
    MONDOSourceAdapter,
    UniProtSourceAdapter,
)


def _mock_release(source_name: str) -> SourceRelease:
    return SourceRelease(
        id=Identifier(namespace="SYS", value=f"{source_name}_rel_1"),
        source_id=Identifier(namespace="SYS", value=source_name),
        version="2026.1",
    )


def test_hgnc_adapter():
    adapter = HGNCSourceAdapter()
    release = _mock_release("hgnc")
    results = adapter.fetch(release)
    assert len(results) == 1
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "HGNC"
    assert obs[0].normalized_id.value == "HGNC:6018"
    assert obs[0].checksum is not None
    assert obs[0].is_approved is False


def test_ensembl_adapter():
    adapter = EnsemblSourceAdapter()
    release = _mock_release("ensembl")
    results = adapter.fetch(release)
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "ENSG"
    assert obs[0].normalized_id.value == "ENSG00000254647"
    assert obs[0].is_approved is False


def test_uniprot_adapter():
    adapter = UniProtSourceAdapter()
    release = _mock_release("uniprot")
    results = adapter.fetch(release)
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "UniProtKB"
    assert obs[0].normalized_id.value == "P01308"
    assert obs[0].is_approved is False


def test_chebi_adapter():
    adapter = ChEBISourceAdapter()
    release = _mock_release("chebi")
    results = adapter.fetch(release)
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "CHEBI"
    assert obs[0].normalized_id.value == "CHEBI:15365"
    assert obs[0].is_approved is False


def test_mondo_adapter():
    adapter = MONDOSourceAdapter()
    release = _mock_release("mondo")
    results = adapter.fetch(release)
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "MONDO"
    assert obs[0].normalized_id.value == "MONDO:0005148"
    assert obs[0].is_approved is False


def test_chembl_adapter():
    adapter = ChEMBLSourceAdapter()
    release = _mock_release("chembl")
    results = adapter.fetch(release)
    obs = adapter.parse_observations(release, results[0])
    assert len(obs) == 1
    assert obs[0].normalized_id.namespace == "CHEMBL"
    assert obs[0].normalized_id.value == "CHEMBL1431"
    assert obs[0].is_approved is False
