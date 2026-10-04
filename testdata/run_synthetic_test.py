"""Self-contained test runner for synthetic knowledge graph fusion.

Usage:
    python testdata/run_synthetic_test.py
"""

from __future__ import annotations

from pathlib import Path

from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService
from infrastructure.storage.assertion_store import DurableAssertionStore


def run_test() -> None:
    ttl_path = Path("testdata/synthetic_graph_a.ttl")
    jsonld_path = Path("testdata/synthetic_graph_b.jsonld")

    print(f"Loading Graph A from: {ttl_path}")
    graph_a_content = ttl_path.read_text(encoding="utf-8")
    print(f"Loading Graph B from: {jsonld_path}")
    graph_b_content = jsonld_path.read_text(encoding="utf-8")

    # 1. Execute Fusion Engine using the 'synthetic' domain preset
    service = GraphFusionService()
    request = GraphFusionRequest(
        graph_a_id="corp_directory_v1",
        graph_a_content=graph_a_content,
        graph_a_format="turtle",
        graph_b_id="hr_screen_v1",
        graph_b_content=graph_b_content,
        graph_b_format="jsonld",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
        domain_preset="synthetic",
    )

    print("\nExecuting 6-Stage Fusion Engine with domain_preset='synthetic'...")
    result = service.execute_fusion(request=request)

    print("\n" + "=" * 65)
    print(" FUSION ENGINE EXECUTION REPORT")
    print("=" * 65)

    stage1 = result.stage_breakdowns.get("stage_1_normalize_data", {})
    print(
        f"Stage 1 [Normalization]: {stage1.get('graph_a_entities', 0)} Graph A nodes, {stage1.get('graph_b_entities', 0)} Graph B nodes"
    )

    stage2 = result.stage_breakdowns.get("stage_2_candidate_matches", {})
    print(
        f"Stage 2 [Candidate Matching]: {stage2.get('candidate_pairs_surfaced', 0)} candidate pairs surfaced"
    )

    stage3 = result.stage_breakdowns.get("stage_3_align_meaning", {})
    print(
        f"Stage 3 [Meaning Alignment]: {stage3.get('meaning_mappings_applied', 0)} mappings applied, {stage3.get('candidates_rejected_ontology', 0)} rejected by ontology"
    )

    stage4 = result.stage_breakdowns.get("stage_4_match_confidence", {})
    print(
        f"Stage 4 [Confidence Decision]: {stage4.get('auto_merged_count', 0)} auto-merged, {stage4.get('review_required_count', 0)} review-required"
    )

    stage5 = result.stage_breakdowns.get("stage_5_canonical_entities_facts", {})
    print(
        f"Stage 5 [Canonicalization]: {stage5.get('deduplicated_facts_count', 0)} duplicate facts deduplicated"
    )

    conflicts = result.conflict_report.get("contradiction_conflicts", [])
    print(f"Stage 6 [Conflict Resolution]: {len(conflicts)} contradiction conflicts detected")
    for c in conflicts:
        print(
            f"    - Opposing pair: ({c.get('winning_predicate_iri')} vs {c.get('losing_predicate_iri')}) on Subject: {c.get('subject_id')}"
        )
        print(f"      Resolution: {c.get('resolution_method')} | Action: {c.get('action')}")

    print(f"\nTotal Reconciled Assertions: {len(result.reconciled_assertions)}")

    # 2. Persist assertions into a test SQLite database
    db_file = Path("data/synthetic_test.db")
    if db_file.exists():
        db_file.unlink()
    store = DurableAssertionStore(db_file)
    store.persist_batch(result.reconciled_assertions, [])
    print(f"Persisted {len(result.reconciled_assertions)} assertions to SQLite: {db_file}")

    print("\nSample Fused Reconciled Assertions:")
    for a in result.reconciled_assertions[:10]:
        print(f"  {a.subject.canonical} --[{a.predicate}]--> {a.object.canonical}")

    # Clean up test SQLite file
    if db_file.exists():
        db_file.unlink()

    print("\n" + "=" * 65)
    print(" SYNTHETIC GRAPH FUSION TEST COMPLETED SUCCESSFULLY")
    print("=" * 65)


if __name__ == "__main__":
    run_test()
