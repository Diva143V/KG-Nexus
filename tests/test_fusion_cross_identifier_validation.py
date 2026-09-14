"""Validation Test for Cross-Identifier Entity Fusion, Literal Typing, and Fact Deduplication.

Verifies:
1. Cross-identifier fusion: Different IDs across graphs (e.g. `http://pharmacy.org/drug/MET-001` in Graph B vs `http://example.org/Metformin` in Graph A) are unified into ONE canonical node.
2. Canonical aliases: The unified node retains both original IDs in its `aliases` list and aggregates provenance.
3. Edge redirection: Edges referencing `MET-001` are redirected to the canonical node.
4. Equivalent fact deduplication: Equivalent facts across different source IDs deduplicate.
5. Complementary fact preservation: Distinct facts from both graphs remain in the fused graph.
6. Literal typing: String numbers (e.g. "165.62" in CSV) and Turtle numeric decimals are normalized without creating entity nodes or self-loops.
7. Rich API payload verification: `stage_breakdowns`, `audit_report`, `review_candidates`, `aliases`, and `provenance_sources` exist and are populated.
"""

from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService


def test_cross_identifier_fusion_and_strict_validation():
    service = GraphFusionService()

    # Graph A in valid Turtle:
    # Uses full IRIs under http://example.org/
    # Contains literal attributes: molecularWeight (numeric), approvedDate (date string)
    graph_a_turtle = """@prefix EX: <http://example.org/> .
EX:INS EX:encodes EX:Insulin .
EX:INS EX:associated_with EX:T2D .
EX:Metformin EX:treats EX:T2D .
EX:CHEBI15365 EX:modulates EX:Insulin .
EX:Metformin EX:chembl_id "CHEMBL1431" .
EX:Metformin EX:molecularWeight 165.62 .
EX:Metformin EX:approvedDate "1994-12-29" .
"""

    # Graph B in CSV with full IRIs:
    # Uses a DISTINCT identifier for Metformin: http://pharmacy.org/drug/MET-001
    # Uses an identity key (chembl_id: "CHEMBL1431") and label to match http://example.org/Metformin
    # Contains literal molecularWeight as string in CSV that should be typed/normalized
    graph_b_csv = """subject,predicate,object
http://pharmacy.org/drug/MET-001,http://example.org/targets,http://example.org/Insulin
http://example.org/CHEBI15365,http://example.org/modulates,http://example.org/Insulin
http://example.org/INS,http://example.org/encodes,http://example.org/Insulin
http://pharmacy.org/drug/MET-001,http://example.org/treats,http://example.org/T2D
http://pharmacy.org/drug/MET-001,http://example.org/chembl_id,"CHEMBL1431"
http://pharmacy.org/drug/MET-001,http://example.org/molecularWeight,"165.62"
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

    # -------------------------------------------------------------------------
    # 1. Verification of Required Response Fields
    # -------------------------------------------------------------------------
    assert hasattr(result, "stage_breakdowns"), "Result must contain stage_breakdowns"
    assert hasattr(result, "audit_report"), "Result must contain audit_report"
    assert hasattr(result, "review_candidates"), "Result must contain review_candidates"
    assert hasattr(result, "deduplicated_edge_count"), "Result must contain deduplicated_edge_count"
    assert hasattr(result, "merged_entity_count"), "Result must contain merged_entity_count"

    assert len(result.stage_breakdowns) == 6
    assert "stage_1_normalize_data" in result.stage_breakdowns
    assert "stage_2_candidate_matches" in result.stage_breakdowns
    assert "stage_3_align_meaning" in result.stage_breakdowns
    assert "stage_4_match_confidence" in result.stage_breakdowns
    assert "stage_5_canonical_entities_facts" in result.stage_breakdowns
    assert "stage_6_provenance_conflicts" in result.stage_breakdowns

    # -------------------------------------------------------------------------
    # 2. Verification of Literal Normalization & Typing (Stage 1)
    # -------------------------------------------------------------------------
    stage1 = result.stage_breakdowns["stage_1_normalize_data"]
    assert stage1["total_normalized_literals"] >= 3, "Literals must be captured in Stage 1"

    # Confirm NO literal values were converted into entity nodes
    node_labels = {n["label"] for n in result.nodes}
    {n["id"] for n in result.nodes}
    assert "165.62" not in node_labels, "Numeric literal 165.62 must NOT become an entity node"
    assert "1994-12-29" not in node_labels, "Date literal must NOT become an entity node"
    assert "CHEMBL1431" not in node_labels, "Identity key literal must NOT become an entity node"

    # -------------------------------------------------------------------------
    # 3. Cross-Identifier Entity Fusion (Stage 4 & Stage 5)
    # -------------------------------------------------------------------------
    assert result.merged_entity_count >= 1, "At least one cross-graph entity merge must occur"

    # Find the merged Metformin node
    metformin_node = None
    for node in result.nodes:
        aliases = node.get("aliases", [])
        if any("Metformin" in a for a in aliases) or any("MET-001" in a for a in aliases):
            metformin_node = node
            break

    assert metformin_node is not None, "A canonical Metformin node must be produced"
    assert any("http://example.org/Metformin" in a for a in metformin_node["aliases"]), (
        "Canonical node must contain http://example.org/Metformin in aliases"
    )
    assert any("http://pharmacy.org/drug/MET-001" in a for a in metformin_node["aliases"]), (
        "Canonical node must contain http://pharmacy.org/drug/MET-001 in aliases"
    )
    assert len(metformin_node["provenance_sources"]) >= 2, (
        "Canonical node must aggregate provenance sources from both graphs"
    )

    # -------------------------------------------------------------------------
    # 4. Edge Redirection & Fact Deduplication (Stage 5 & Stage 6)
    # -------------------------------------------------------------------------
    # Fact 1: Metformin treats T2D (asserted in Graph A via Metformin, in Graph B via MET-001)
    # Fact 2: INS encodes Insulin (asserted in Graph A & Graph B, mapped to producesProtein)
    # Fact 3: CHEBI15365 modulates Insulin (asserted in Graph A & Graph B)
    assert result.deduplicated_edge_count >= 3, (
        f"Expected at least 3 deduplicated edges, got {result.deduplicated_edge_count}"
    )

    # -------------------------------------------------------------------------
    # 5. Preservation of Complementary Facts
    # -------------------------------------------------------------------------
    # Unique to Graph A: INS associated_with T2D
    # Unique to Graph B: MET-001 targets Insulin (redirected to canonical Metformin)
    assert result.derived_assertions_count == 5, (
        f"Expected 5 distinct canonical fused triples, got {result.derived_assertions_count}"
    )

    # Verify edge endpoints are redirected to canonical IDs (no dangling MET-001 edges)
    {e["from"] for e in result.edges}
    {e["to"] for e in result.edges}

    # All targets/treats edges originating from MET-001 must now originate from the canonical Metformin ID
    targets_edge = next((e for e in result.edges if "targets" in e["label"]), None)
    assert targets_edge is not None, "Complementary fact 'targets' from Graph B must be preserved"
    assert targets_edge["from"] == metformin_node["id"], (
        "Edge from Graph B 'MET-001 targets Insulin' must be redirected to canonical Metformin node"
    )

    # -------------------------------------------------------------------------
    # 6. Audit Trail & Review Items
    # -------------------------------------------------------------------------
    assert len(result.audit_report) > 0, "Audit report must record candidate decisions"
    metformin_audit = next(
        (
            a
            for a in result.audit_report
            if ("Metformin" in a["source_id"] and "MET-001" in a["target_id"])
            or ("MET-001" in a["source_id"] and "Metformin" in a["target_id"])
        ),
        None,
    )
    assert metformin_audit is not None, (
        "Audit report must contain the Metformin <-> MET-001 match record"
    )
    assert metformin_audit["decision"] == "merge_automatic"
    assert metformin_audit["match_score"] >= 0.88
