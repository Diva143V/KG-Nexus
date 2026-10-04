"""End-to-end integration test verifying fusion and drug repurposing across complementary test graphs."""

from __future__ import annotations

from pathlib import Path

from applications.drug_repurposing.workflow import AssertionStoreLayers, DrugRepurposingPipeline
from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from infrastructure.storage.assertion_store import DurableAssertionStore


def test_e2e_dataset_fusion_and_drug_repurposing(tmp_path: Path) -> None:
    ttl_path = Path("testdata/test_graph_a.ttl")
    jsonld_path = Path("testdata/test_graph_b.jsonld")

    assert ttl_path.exists(), f"Missing dataset: {ttl_path}"
    assert jsonld_path.exists(), f"Missing dataset: {jsonld_path}"

    ttl_content = ttl_path.read_text(encoding="utf-8")
    jsonld_content = jsonld_path.read_text(encoding="utf-8")

    # 1. Execute 6-stage fusion engine
    service = GraphFusionService()
    fusion_request = GraphFusionRequest(
        graph_a_id="clinical_oncology_v1",
        graph_a_content=ttl_content,
        graph_a_format="turtle",
        graph_b_id="pharmacology_screen_v1",
        graph_b_content=jsonld_content,
        graph_b_format="jsonld",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
        domain_preset="biomedical",
    )
    result = service.execute_fusion(request=fusion_request)

    # Verify stage breakdown metrics
    stage1 = result.stage_breakdowns.get("stage_1_normalize_data", {})
    assert stage1.get("graph_a_entities", 0) > 0
    assert stage1.get("graph_b_entities", 0) > 0

    stage2 = result.stage_breakdowns.get("stage_2_candidate_matches", {})
    assert stage2.get("candidate_pairs_surfaced", 0) >= 20

    stage3 = result.stage_breakdowns.get("stage_3_align_meaning", {})
    assert stage3.get("candidates_rejected_ontology", 0) >= 1

    stage4 = result.stage_breakdowns.get("stage_4_match_confidence", {})
    assert stage4.get("auto_merged_count", 0) >= 5

    stage5 = result.stage_breakdowns.get("stage_5_canonical_entities_facts", {})
    assert stage5.get("deduplicated_facts_count", 0) >= 1

    conflicts = result.conflict_report.get("contradiction_conflicts", [])
    assert len(conflicts) >= 1
    opposing_conflict = conflicts[0]
    assert opposing_conflict["conflict_category"] == "CONTRADICTORY_PREDICATE_CONFLICT"
    assert (
        "treats" in opposing_conflict["winning_predicate_iri"]
        or "treats" in opposing_conflict["losing_predicate_iri"]
    )

    assert len(result.reconciled_assertions) >= 40

    # 2. Persist to Durable SQLite Assertion Store
    db_file = tmp_path / "test_assertions.db"
    store = DurableAssertionStore(db_file)
    store.persist_batch(result.reconciled_assertions, [])

    # 3. Drug Repurposing Pipeline Discovery
    target_disease = Identifier(namespace="MONDO", value="0005267")  # NSCLC
    pipeline = DrugRepurposingPipeline(
        agent_id=Identifier(namespace="AGENT", value="repurposing_pilot"),
        activity_id=Identifier(namespace="ACTIVITY", value="act_pilot_test"),
    )
    layers = AssertionStoreLayers(production=list(result.reconciled_assertions))
    hypotheses = pipeline.generate_hypotheses(
        target_disease_id=target_disease,
        layers=layers,
    )

    assert len(hypotheses) >= 1
    drug_ids = [h.drug_id.value for h in hypotheses]
    # Check that Osimertinib or candidate Aspirin was discovered
    assert any("3353410" in did or "25" in did for did in drug_ids)
    for h in hypotheses:
        assert h.target_layer == "hypothesis"
        assert len(h.input_assertion_refs) >= 3
