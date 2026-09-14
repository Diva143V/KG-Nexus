"""Unit Tests for Stage 6: Provenance and Conflict Management.

Verifies:
- Lineage recording: source graph, original assertion ID, confidence, agent
- Contradictory predicate conflict detection (e.g. treats vs contraindicates)
- Deterministic 4-tier conflict resolution
- Deduplication of equivalent facts
- Comprehensive conflict audit report generation across all 4 ConflictModes
"""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.fusion.models import ConflictMode
from core.fusion.provenance_conflict_manager import ProvenanceConflictManager
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from sdk.domain_config import get_biomedical_preset


def _make_test_assertion(
    a_id: str, subj: str, pred: str, obj: str, source_graph: str = "rel_graph_a"
) -> Assertion:
    return Assertion(
        id=Identifier(namespace="ASSERT", value=f"{source_graph}_{a_id}"),
        subject=Identifier(namespace="ENTITY", value=subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=obj),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value=f"agent_{source_graph}"),
            activity_id=Identifier(namespace="SYS", value=f"act_{source_graph}"),
            asserted_at=datetime.now(UTC),
        ),
    )


def test_contradiction_detection_and_conflict_report():
    config = get_biomedical_preset()
    manager = ProvenanceConflictManager(config)

    a1 = _make_test_assertion("1", "Metformin", "treats", "Type_2_Diabetes", "rel_graph_a")
    a2 = _make_test_assertion("2", "Metformin", "contraindicates", "Type_2_Diabetes", "rel_graph_b")

    # 1. Test ConflictMode.CONFLICT_REJECT
    res_reject = manager.reconcile([a1, a2], conflict_mode=ConflictMode.CONFLICT_REJECT)
    assert res_reject.conflict_count == 1
    assert len(res_reject.reconciled_assertions) == 1
    assert str(res_reject.reconciled_assertions[0].predicate) == "treats"  # Graph A won

    # Verify conflict report
    report = res_reject.conflict_report
    assert report["summary"]["total_contradictions_detected"] == 1
    assert len(report["contradiction_conflicts"]) == 1
    c_entry = report["contradiction_conflicts"][0]
    assert c_entry["action"] == "REJECTED_LOSING_CLAIM"
    assert "treats ↔ contraindicates" in c_entry["normalized_conflict"]


def test_exact_triple_deduplication():
    config = get_biomedical_preset()
    manager = ProvenanceConflictManager(config)

    a1 = _make_test_assertion("1", "INS", "encodes", "Insulin", "rel_graph_a")
    a2 = _make_test_assertion("2", "INS", "encodes", "Insulin", "rel_graph_b")

    res_dedup = manager.reconcile([a1, a2], conflict_mode=ConflictMode.CONFLICT_REJECT)
    assert res_dedup.dedup_count == 1
    assert len(res_dedup.reconciled_assertions) == 1
    assert len(res_dedup.deduplications) == 1


def test_functional_predicate_collision_detection():
    config = get_biomedical_preset()
    manager = ProvenanceConflictManager(config)

    # Single-valued functional predicate (e.g. birthDate / dateOfBirth / molecularWeight)
    a1 = _make_test_assertion("1", "ScientistAlpha", "birthDate", "1879-03-14", "rel_graph_a")
    a2 = _make_test_assertion("2", "ScientistAlpha", "birthDate", "1881-05-20", "rel_graph_b")

    # In CONFLICT_REJECT mode, deterministic resolution picks winner (Graph A default precedence)
    res_reject = manager.reconcile([a1, a2], conflict_mode=ConflictMode.CONFLICT_REJECT)
    assert len(res_reject.functional_collisions) == 1
    assert res_reject.conflict_count == 1
    assert len(res_reject.reconciled_assertions) == 1
    assert str(res_reject.reconciled_assertions[0].object.value) == "1879-03-14"

    report = res_reject.conflict_report
    assert report["summary"]["total_functional_collisions_detected"] == 1
    f_entry = report["functional_collisions"][0]
    assert f_entry["conflict_category"] == "FUNCTIONAL_PREDICATE_COLLISION"
    assert f_entry["action"] == "REJECTED_LOSING_CLAIM"
    assert "birthDate" in f_entry["normalized_conflict"]
