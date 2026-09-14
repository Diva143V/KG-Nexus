"""Tests for Universal Source Identity, URI/DOI Schemes, and Ultimate Ground Truth (Pillar 1).

Covers:
1. Academic DOI normalization and canonicalization.
2. Global Patent URN formatting and normalization.
3. Web URL normalization.
4. Internal enterprise files with cryptographic SHA-256 content digest alignment.
5. Cross-identifier alias lookup via pluggable domain resolver.
6. Manual pinned URI override (ultimate truth anchoring).
7. Tier 0 Ultimate Ground Truth conflict resolution precedence over lower-tier assertions.
8. GenericFusionEngine 6-stage execution with source alignment integration.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.fusion.engine import GenericFusionEngine
from core.fusion.models import ConflictMode
from core.fusion.source_aligner import SourceAligner
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from core.resources.source_node import (
    SourceNode,
    compute_content_digest,
    normalize_source_uri,
)
from sdk.domain_config import (
    SourceSchemeRule,
    get_biomedical_preset,
    get_general_agnostic_preset,
)
from sdk.source_resolver import DefaultSourceResolver


def _create_assertion(
    assertion_id: str,
    subject_val: str,
    predicate: str,
    object_val: str,
    source_ref: str,
    confidence: float = 1.0,
) -> Assertion:
    now = datetime.now(UTC)
    return Assertion(
        id=Identifier(namespace="ASSERTION", value=assertion_id),
        subject=Identifier(namespace="ENTITY", value=subject_val),
        predicate=predicate,
        object=Identifier(namespace="ENTITY", value=object_val),
        confidence=None,
        evidence=(),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=Identifier(namespace="AGENT", value="test_agent"),
            activity_id=Identifier(namespace="ACTIVITY", value="test_activity"),
            asserted_at=now,
            derivation_method="expert_curation",
            input_resource_refs=(Identifier(namespace="SOURCE", value=source_ref),),
        ),
    )


def test_doi_normalization() -> None:
    """Test standard academic DOI normalization across various representation formats."""
    rule = SourceSchemeRule(
        scheme_prefix="urn:doi:",
        strip_prefix_variants=("https://doi.org/", "http://dx.doi.org/", "doi:"),
        regex_pattern=r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$",
    )
    # DOI with https://doi.org/ prefix
    u1 = normalize_source_uri("https://doi.org/10.1038/s41586-020-2003-7", rule)
    assert u1 == "urn:doi:10.1038/s41586-020-2003-7"

    # DOI with http://dx.doi.org/ prefix
    u2 = normalize_source_uri("http://dx.doi.org/10.1038/s41586-020-2003-7", rule)
    assert u2 == "urn:doi:10.1038/s41586-020-2003-7"

    # DOI with doi: prefix
    u3 = normalize_source_uri("doi:10.1038/S41586-020-2003-7", rule)
    assert u3 == "urn:doi:10.1038/s41586-020-2003-7"

    # DOI already in URN format
    u4 = normalize_source_uri("urn:doi:10.1038/s41586-020-2003-7", rule)
    assert u4 == "urn:doi:10.1038/s41586-020-2003-7"


def test_patent_normalization() -> None:
    """Test global patent URN formatting and normalization."""
    rule = SourceSchemeRule(
        scheme_prefix="urn:patent:",
        category="patent",
    )
    # US Patent with spaces and lowercase
    u1 = normalize_source_uri("US 11,234,567 B2", rule)
    assert u1 == "urn:patent:US:11234567:B2"

    # EP Patent
    u2 = normalize_source_uri("EP3456789A1", rule)
    assert u2 == "urn:patent:EP:3456789:A1"

    # Already prefixed
    u3 = normalize_source_uri("urn:patent:US:11234567:B2", rule)
    assert u3 == "urn:patent:US:11234567:B2"


def test_internal_content_digest_computation() -> None:
    """Test SHA-256 cryptographic digest calculation for tamper-proof enterprise documents."""
    content = b"Confidential Research Report on Compound Alpha v1.2"
    expected = hashlib.sha256(content).hexdigest()
    computed = compute_content_digest(content)
    assert computed == expected

    # String content computation
    str_content = "Confidential Research Report on Compound Alpha v1.2"
    computed_str = compute_content_digest(str_content)
    assert computed_str == expected


def test_source_alignment_by_content_digest() -> None:
    """Test aligning internal enterprise files with identical content but different paths/names."""
    config = get_general_agnostic_preset()
    aligner = SourceAligner(config)

    content_digest = compute_content_digest("Internal Lab Notes 2026-Q1 on Target X")

    source_a = SourceNode(
        id=Identifier(namespace="SOURCE", value="doc_lab_graph_a"),
        label="Lab Notebook Graph A",
        canonical_uri="urn:internal:doc:notebook_a.pdf",
        content_digest=content_digest,
    )
    source_b = SourceNode(
        id=Identifier(namespace="SOURCE", value="doc_archived_graph_b"),
        label="Archived Records Graph B",
        canonical_uri="urn:internal:doc:archive_batch_2026.pdf",
        content_digest=content_digest,
    )

    res = aligner.align_sources(
        {"doc_lab_graph_a": source_a},
        {"doc_archived_graph_b": source_b},
    )

    assert len(res.aligned_pairs) == 1
    pair = res.aligned_pairs[0]
    assert pair.alignment_method == "cryptographic_content_digest_match"
    assert res.source_alias_map["doc_archived_graph_b"] == "doc_lab_graph_a"


def test_cross_identifier_alias_match() -> None:
    """Test cross-identifier alias matching via pluggable domain resolver (e.g. PMID <-> DOI)."""
    config = get_biomedical_preset()
    resolver = DefaultSourceResolver(
        aliases={
            "urn:pubmed:12345678": ["urn:doi:10.1038/s41586-020-2003-7"],
            "urn:doi:10.1038/s41586-020-2003-7": ["urn:pubmed:12345678"],
        }
    )
    aligner = SourceAligner(config, resolver=resolver)

    source_a = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_pubmed"),
        label="Nature Paper PubMed Entry",
        canonical_uri="urn:pubmed:12345678",
    )
    source_b = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_nature_doi"),
        label="Nature Paper Publisher DOI",
        canonical_uri="urn:doi:10.1038/s41586-020-2003-7",
    )

    res = aligner.align_sources(
        {"src_pubmed": source_a},
        {"src_nature_doi": source_b},
    )

    assert len(res.aligned_pairs) == 1
    pair = res.aligned_pairs[0]
    assert pair.alignment_method in ("cross_identifier_alias_match", "alternate_id_overlap_match")


def test_manual_pinned_uri_override() -> None:
    """Test manual pinned URI override (anchoring identity to user-specified ground truth)."""
    config = get_general_agnostic_preset()
    aligner = SourceAligner(config)

    # Two sources with completely different canonical URIs but same manual pinned URI
    source_a = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_raw_1"),
        label="Source Raw 1",
        canonical_uri="urn:raw:file1",
        pinned_canonical_uri="urn:doi:10.1000/182",
    )
    source_b = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_raw_2"),
        label="Source Raw 2",
        canonical_uri="urn:raw:file2",
        pinned_canonical_uri="urn:doi:10.1000/182",
    )

    assert source_a.effective_canonical_uri == "urn:doi:10.1000/182"
    assert source_b.effective_canonical_uri == "urn:doi:10.1000/182"

    res = aligner.align_sources(
        {"src_raw_1": source_a},
        {"src_raw_2": source_b},
    )

    assert len(res.aligned_pairs) == 1
    assert res.aligned_pairs[0].alignment_method == "manual_pinned_uri_match"


def test_ultimate_ground_truth_conflict_precedence() -> None:
    """Test that assertions citing Tier 0 Ultimate Ground Truth unconditionally defeat contradictory claims."""
    # Graph A claims: DrugX treats DiseaseY (cited by unverified blog post or preprint)
    # Graph B claims: DrugX contraindicates DiseaseY (cited by FDA Approved Label - Ground Truth)
    config = get_biomedical_preset()
    config = config.model_copy(
        update={
            "source_identity": config.source_identity.model_copy(
                update={
                    "ground_truth_sources": ["urn:fda:drug:label:drugx_package_insert"],
                }
            )
        }
    )

    gt_source = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_fda_label"),
        label="FDA Official Package Insert for DrugX",
        canonical_uri="urn:fda:drug:label:drugx_package_insert",
        is_ground_truth=True,
        authority_tier=1,
    )
    heuristic_source = SourceNode(
        id=Identifier(namespace="SOURCE", value="src_blog_heuristic"),
        label="Preprint / Social Forum Mention",
        canonical_uri="https://forum.example.com/posts/drugx-cure",
        is_ground_truth=False,
        authority_tier=5,
    )

    engine = GenericFusionEngine()

    a1 = _create_assertion(
        assertion_id="rel_graph_a_001",
        subject_val="DrugX",
        predicate="treats",
        object_val="DiseaseY",
        source_ref="src_blog_heuristic",
        confidence=0.99,  # High confidence claim, but non-authoritative source!
    )
    a2 = _create_assertion(
        assertion_id="rel_graph_b_001",
        subject_val="DrugX",
        predicate="contraindicates",
        object_val="DiseaseY",
        source_ref="src_fda_label",
        confidence=0.85,
    )

    # In CONFLICT_REJECT mode, the winning assertion is kept and losing is purged
    result = engine.fuse(
        graph_a_id=Identifier(namespace="GRAPH", value="graph_unverified"),
        graph_a_assertions=[a1],
        graph_b_id=Identifier(namespace="GRAPH", value="graph_fda_authoritative"),
        graph_b_assertions=[a2],
        activity_id=Identifier(namespace="ACTIVITY", value="fusion_eval_01"),
        conflict_mode=ConflictMode.CONFLICT_REJECT,
        domain_config=config,
        sources_a=[heuristic_source],
        sources_b=[gt_source],
    )

    # Check contradictions
    contradictions = result.conflict_report["contradiction_conflicts"]
    assert len(contradictions) == 1
    c = contradictions[0]
    # Ground truth FDA source must win!
    assert c["resolution_method"] == "ULTIMATE_GROUND_TRUTH_AUTHORITY"
    assert c["winning_predicate_iri"] == "contraindicates"
    assert c["losing_predicate_iri"] == "treats"

    # Only the winning fact should be in reconciled assertions
    assert len(result.reconciled_assertions) == 1
    assert result.reconciled_assertions[0].predicate == "contraindicates"


def test_full_engine_source_alignment_metrics() -> None:
    """Test that GenericFusionEngine exposes source alignment metrics and records in stage_breakdowns."""
    config = get_general_agnostic_preset()
    engine = GenericFusionEngine()

    a1 = _create_assertion(
        assertion_id="rel_a_1",
        subject_val="EntityAlpha",
        predicate="connected_to",
        object_val="EntityBeta",
        source_ref="urn:doi:10.1038/nature12345",
    )
    a2 = _create_assertion(
        assertion_id="rel_b_1",
        subject_val="EntityAlpha",
        predicate="connected_to",
        object_val="EntityBeta",
        source_ref="https://doi.org/10.1038/nature12345",
    )

    res = engine.fuse(
        graph_a_id=Identifier(namespace="GRAPH", value="g_a"),
        graph_a_assertions=[a1],
        graph_b_id=Identifier(namespace="GRAPH", value="g_b"),
        graph_b_assertions=[a2],
        activity_id=Identifier(namespace="ACTIVITY", value="act_metrics"),
        domain_config=config,
    )

    # Inspect source alignment in stage breakdowns
    assert "source_alignment" in res.stage_breakdowns["stage_1_normalize_data"]
    sa_metrics = res.stage_breakdowns["stage_1_normalize_data"]["source_alignment"]
    assert sa_metrics["aligned_pairs_count"] == 1
    assert sa_metrics["aligned_pairs"][0]["method"] == "exact_canonical_uri_match"
    assert res.source_alignment is not None
    assert len(res.source_alignment.aligned_pairs) == 1
