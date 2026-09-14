"""Integration Tests for Critical Bug Fixes and Architectural Improvements.

Validates:
1. Literal assertions survival through Stage 1 -> Stage 3 -> Stage 5 -> Stage 6.
2. Class mapping execution with consistent (concept, graph_role) keys.
3. Attribute alignment execution on literal assertions.
4. Configured candidate matching weights and similarity thresholds.
5. Custom Graph ID handling without hardcoded 'rel_graph_a' string matching.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.fusion.candidate_finder import CandidateFinder
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.normalizer import NormalizedGraph
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from core.resolution.models import CandidateMatch
from sdk.domain_config import (
    DomainFusionConfig,
    EntityTypeConfig,
    MappingDirection,
    MatchStrategyConfig,
    MeaningAlignmentConfig,
    MeaningMapping,
)


def _make_test_provenance(agent_name: str, activity_name: str) -> Provenance:
    return Provenance(
        agent_id=Identifier(namespace="AGENT", value=agent_name),
        activity_id=Identifier(namespace="ACT", value=activity_name),
        asserted_at=datetime.now(UTC),
    )


def test_literal_assertions_survive_full_fusion_pipeline():
    """Test 1: Verify literal assertions survive Stages 1 -> 3 -> 5 -> 6 and appear in the fused result."""
    service = GraphFusionService()

    # Graph A has both a relational assertion and a literal assertion
    graph_a_ttl = """
    @prefix exa: <http://example.org/a/> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    exa:Metformin a exa:Drug ;
        rdfs:label "Metformin" ;
        exa:chemicalFormula "C4H11N5" ;
        exa:treats exa:Type2Diabetes .
    """

    # Graph B has an alias entity and another literal assertion
    graph_b_ttl = """
    @prefix exb: <http://example.org/b/> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    exb:Metformin_Drug a exb:Medication ;
        rdfs:label "Metformin" ;
        exb:molecularWeight "129.16" .
    """

    req = GraphFusionRequest(
        graph_a_id="source_a",
        graph_b_id="source_b",
        graph_a_content=graph_a_ttl,
        graph_a_format="turtle",
        graph_b_content=graph_b_ttl,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
    )

    result = service.execute_fusion(req)

    # 1. Verify entities merged
    assert result.merged_entity_count >= 1

    # 2. Verify literal assertions survived in the output nodes' properties
    # Find the fused Metformin node
    metformin_node = next(
        (
            n
            for n in result.nodes
            if "Metformin" in n.get("canonical_id", "") or "Metformin" in n.get("id", "")
        ),
        None,
    )
    assert metformin_node is not None, "Metformin entity should exist in fused nodes"

    props = metformin_node.get("properties", {})
    # Chemical formula and molecular weight should have survived through the pipeline
    found_formula = any("C4H11N5" in str(v) for v in props.values())
    found_weight = any("129.16" in str(v) for v in props.values())
    assert found_formula, (
        f"Literal assertion C4H11N5 must survive pipeline into node properties: {props}"
    )
    assert found_weight, (
        f"Literal assertion 129.16 must survive pipeline into node properties: {props}"
    )


def test_class_mapping_execution():
    """Test 2: Verify class mappings are matched and applied with (concept, 'graph_a') keys."""
    mapping = MeaningMapping(
        source_concept="AntidiabeticAgent",
        target_concept="Drug",
        direction=MappingDirection.DIRECTED_A_TO_B,
    )
    meaning_cfg = MeaningAlignmentConfig(class_mappings=(mapping,))
    domain_cfg = DomainFusionConfig(
        meaning_alignment=meaning_cfg,
        entity_types=(
            EntityTypeConfig(name="AntidiabeticAgent", namespace_prefixes=("antidiabetic",)),
        ),
    )
    aligner = MeaningAligner(domain_config=domain_cfg)

    e1 = Entity(
        id=Identifier(namespace="EX", value="http://example.org/antidiabetic/Metformin"),
        kind=EntityKind.CONCEPT,
        label="Metformin",
    )
    e2 = Entity(
        id=Identifier(namespace="EX", value="http://example.org/drugs/Metformin_HCl"),
        kind=EntityKind.CONCEPT,
        label="Metformin HCl",
    )

    cand = CandidateMatch(
        source_entity=e1,
        candidate_entity=e2,
        ranking_score=0.92,
        ranking_method="normalized_label",
        activity_id=Identifier(namespace="ACT", value="act_align_test"),
    )

    norm_a = NormalizedGraph(
        graph_id="graph_a", entities={"http://example.org/antidiabetic/Metformin": e1}
    )
    norm_b = NormalizedGraph(
        graph_id="graph_b", entities={"http://example.org/drugs/Metformin_HCl": e2}
    )
    result = aligner.align_candidates([cand], norm_a, norm_b)
    assert result.mappings_applied_count == 1
    assert len(result.mappings_applied_log) == 1
    assert any(
        "Class mapping: AntidiabeticAgent ↔ Drug" in m
        for log in result.mappings_applied_log
        for m in log["mappings"]
    )


def test_attribute_alignment_on_literal_assertions():
    """Test 3: Verify attribute alignment maps literal predicates according to domain config."""
    mapping = MeaningMapping(
        source_concept="fullName",
        target_concept="name",
        direction=MappingDirection.EQUIVALENT,
    )
    meaning_cfg = MeaningAlignmentConfig(attribute_mappings=(mapping,))
    domain_cfg = DomainFusionConfig(meaning_alignment=meaning_cfg)
    aligner = MeaningAligner(domain_config=domain_cfg)

    prov = _make_test_provenance("agent_a", "act_a")
    lit_assertion = Assertion(
        id=Identifier(namespace="ASSERT", value="lit_1"),
        subject=Identifier(namespace="ENTITY", value="http://example.org/entity_1"),
        predicate="fullName",
        object=Identifier(namespace="LITERAL", value="Acetylsalicylic_Acid"),
        provenance=prov,
    )

    norm_graph = NormalizedGraph(graph_id="graph_a", literal_assertions=[lit_assertion])
    aligned_assertions = aligner.align_assertions(
        norm_graph,
        graph_name="graph_a",
    )

    assert len(aligned_assertions) == 1
    aligned_lit = aligned_assertions[0]
    assert aligned_lit.predicate == "name"
    assert aligned_lit.object.value == "Acetylsalicylic_Acid"


def test_configured_candidate_weights_alter_composite_scoring():
    """Test 4: Verify custom matching weights in MatchStrategyConfig alter candidate ranking composite scores."""
    # Strategy 1: High exact ID weight, zero structural / embedding
    strat_exact = MatchStrategyConfig(
        exact_id_weight=0.9,
        label_similarity_weight=0.1,
        structural_similarity_weight=0.0,
        embedding_weight=0.0,
    )
    cfg1 = DomainFusionConfig(match_strategy=strat_exact)
    finder1 = CandidateFinder(domain_config=cfg1)

    # Strategy 2: Heavy label similarity and structural similarity weight
    strat_label = MatchStrategyConfig(
        exact_id_weight=0.1,
        label_similarity_weight=0.5,
        structural_similarity_weight=0.2,
        embedding_weight=0.2,
    )
    cfg2 = DomainFusionConfig(match_strategy=strat_label)
    finder2 = CandidateFinder(domain_config=cfg2)

    # Entities with same label but different IDs
    e1 = Entity(
        id=Identifier(namespace="EX_A", value="Node_1234"),
        kind=EntityKind.CONCEPT,
        label="Cardiovascular Disease",
    )
    e2 = Entity(
        id=Identifier(namespace="EX_B", value="Node_9999"),
        kind=EntityKind.CONCEPT,
        label="Cardiovascular Disease",
    )

    norm_a = NormalizedGraph(graph_id="graph_a", entities={"Node_1234": e1})
    norm_b = NormalizedGraph(graph_id="graph_b", entities={"Node_9999": e2})

    act_id = Identifier(namespace="ACT", value="test_act")
    candidates1 = finder1.find_candidates(norm_a, norm_b, activity_id=act_id)
    candidates2 = finder2.find_candidates(norm_a, norm_b, activity_id=act_id)

    assert len(candidates1) == 1
    assert len(candidates2) == 1

    cand1 = candidates1[0]
    cand2 = candidates2[0]

    # In cand1, exact_id (0.0) * 0.9 + label (1.0) * 0.1 = 0.10
    # In cand2, exact_id (0.0) * 0.1 + label (1.0) * 0.5 + struct * 0.2 + embed * 0.2 >= 0.50
    assert cand2.composite_score > cand1.composite_score
    assert cand1.composite_score == pytest.approx(0.10, abs=0.05)
    assert cand2.composite_score >= 0.45


def test_custom_graph_ids_without_rel_graph_substring():
    """Test 5: Verify arbitrary custom graph IDs without 'rel_graph_a' behave correctly."""
    service = GraphFusionService()

    graph_alpha = """
    @prefix alpha: <http://custom.alpha.org/> .
    alpha:CompoundX alpha:treats alpha:SyndromeY .
    """

    graph_beta = """
    @prefix beta: <http://custom.beta.org/> .
    beta:CompoundX beta:contraindicates beta:SyndromeY .
    """

    # Custom graph IDs: "dataset_alpha" and "dataset_beta"
    req = GraphFusionRequest(
        graph_a_id="dataset_alpha",
        graph_b_id="dataset_beta",
        graph_a_content=graph_alpha,
        graph_a_format="turtle",
        graph_b_content=graph_beta,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_REJECT,
    )

    result = service.execute_fusion(req)

    # Should detect 1 contradiction between treats and contraindicates
    assert result.conflict_report["summary"]["total_contradictions_detected"] == 1

    # Deterministic winner should be dataset_alpha's claim ("treats")
    assert len(result.edges) == 1
    assert "treats" in result.edges[0]["label"]
    conflict_entry = result.conflict_report["contradiction_conflicts"][0]
    assert "treats" in conflict_entry["winning_predicate_iri"]
    assert "contraindicates" in conflict_entry["losing_predicate_iri"]
