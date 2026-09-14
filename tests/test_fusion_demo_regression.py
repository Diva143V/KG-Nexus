"""Regression Tests for Knowledge Graph Fusion Demo Scenario.

Verifies:
- Four entity pairs merge across Graph A & Graph B (INS, Insulin, Metformin, CHEBI15365).
- Equivalent edges deduplicate properly.
- Distinct complementary facts remain preserved in the fused graph.
- Full 6-stage execution summary is produced with audit report.
"""

from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService


def test_four_entity_pairs_merge_dedup_and_preserve_facts():
    service = GraphFusionService()

    graph_a_turtle = """
    @prefix EX: <http://example.org/> .
    EX:INS EX:encodes EX:Insulin .
    EX:INS EX:associated_with EX:T2D .
    EX:Metformin EX:treats EX:T2D .
    EX:CHEBI15365 EX:modulates EX:Insulin .
    """

    graph_b_csv = """subject,predicate,object
EX:Metformin,targets,EX:Insulin
EX:CHEBI15365,modulates,EX:Insulin
EX:INS,encodes,EX:Insulin
EX:Metformin,treats,EX:T2D
"""

    req = GraphFusionRequest(
        graph_a_content=graph_a_turtle,
        graph_a_format="turtle",
        graph_b_content=graph_b_csv,
        graph_b_format="csv",
        conflict_mode=ConflictMode.CONFLICT_REJECT,
        domain_preset="biomedical",
    )

    result = service.execute_fusion(req)

    # 1. Total input assertions = 4 in A + 4 in B = 8
    assert result.total_input_assertions == 8

    # 2. Equivalent edges deduplicated = 3
    # (INS encodes Insulin, CHEBI15365 modulates Insulin, Metformin treats T2D)
    assert result.deduplicated_edge_count == 3

    # 3. Derived assertions = 5 distinct facts
    # 1. INS encodes Insulin
    # 2. INS associated_with T2D (unique to Graph A)
    # 3. Metformin treats T2D
    # 4. CHEBI15365 modulates Insulin
    # 5. Metformin targets Insulin (unique to Graph B)
    assert result.derived_assertions_count == 5
    assert len(result.edges) == 5

    # 4. Check 4 key entity pairs merged and nodes created
    node_ids = {n["id"] for n in result.nodes}
    assert any("INS" in nid for nid in node_ids)
    assert any("Insulin" in nid for nid in node_ids)
    assert any("Metformin" in nid for nid in node_ids)
    assert any("CHEBI15365" in nid for nid in node_ids)
    assert any("T2D" in nid for nid in node_ids)

    # 5. Check 6-stage execution summary
    sb = result.stage_breakdowns
    assert "stage_1_normalize_data" in sb
    assert "stage_2_candidate_matches" in sb
    assert "stage_3_align_meaning" in sb
    assert "stage_4_match_confidence" in sb
    assert "stage_5_canonical_entities_facts" in sb
    assert "stage_6_provenance_conflicts" in sb

    # 6. Check audit report has entries
    assert len(result.audit_report) > 0
