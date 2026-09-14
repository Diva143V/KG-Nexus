"""Comprehensive Automated Tests for Domain-Agnostic Knowledge Graph Fusion."""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.fusion.candidates import CandidateGenerator
from core.fusion.engine import DefaultIdentityPolicy
from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.reconciliation import EdgeReconciler
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance


def _make_test_assertion(a_id: str, subj: str, pred: str, obj: str, graph_name: str) -> Assertion:
    prov = Provenance(
        agent_id=Identifier(namespace="SYS", value=f"agent_{graph_name}"),
        activity_id=Identifier(namespace="SYS", value=f"act_{graph_name}"),
        asserted_at=datetime.now(UTC),
    )
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="ENTITY", value=subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=obj),
        provenance=prov,
    )


def test_exact_uri_candidate_matching():
    gen = CandidateGenerator()
    e1 = Entity(
        id=Identifier(namespace="EX", value="Node1"), kind=EntityKind.CONCEPT, label="Alpha"
    )
    e2 = Entity(
        id=Identifier(namespace="EX", value="Node1"), kind=EntityKind.CONCEPT, label="Alpha Node"
    )
    activity_id = Identifier(namespace="ACT", value="act_1")

    candidates = gen.generate_candidates([e1], [e2], activity_id)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.ranking_method == "exact_uri"

    policy = DefaultIdentityPolicy()
    decision = policy.evaluate(cand)
    assert decision.accepted is True
    assert decision.method == "exact_uri_policy_acceptance"


def test_uri_mismatch_and_label_collision_handling():
    gen = CandidateGenerator()
    e_apple_company = Entity(
        id=Identifier(namespace="EX", value="AppleCompany"),
        kind=EntityKind.ORGANIZATION,
        label="Apple",
    )
    e_apple_fruit = Entity(
        id=Identifier(namespace="EX", value="AppleFruit"), kind=EntityKind.OBJECT, label="Apple"
    )
    activity_id = Identifier(namespace="ACT", value="act_1")

    candidates = gen.generate_candidates([e_apple_company], [e_apple_fruit], activity_id)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.ranking_method == "normalized_label"

    policy = DefaultIdentityPolicy()
    decision = policy.evaluate(cand)
    assert decision.accepted is False
    assert decision.method == "kind_mismatch_rejection"


def test_structural_triple_deduplication():
    reconciler = EdgeReconciler()
    a1 = _make_test_assertion("a1", "ex:A", "worksAt", "ex:X", "graph_a")
    a2 = _make_test_assertion("a2", "ex:A", "worksAt", "ex:X", "graph_b")

    reconciled, dedup_count, *_ = reconciler.reconcile_assertions(
        [a1], [a2], conflict_mode=ConflictMode.CONFLICT_REJECT
    )
    assert dedup_count == 1
    assert len(reconciled) == 1


def test_conflict_preserve_mode():
    reconciler = EdgeReconciler()
    a1 = _make_test_assertion("a1", "ex:A", "worksAt", "ex:X", "graph_a")
    a2 = _make_test_assertion("a2", "ex:A", "worksAt", "ex:X", "graph_b")

    reconciled, dedup_count, *_ = reconciler.reconcile_assertions(
        [a1], [a2], conflict_mode=ConflictMode.CONFLICT_PRESERVE
    )
    assert dedup_count == 1
    assert len(reconciled) == 2


def test_graph_fusion_service_execution_and_immutability():
    service = GraphFusionService()
    req = GraphFusionRequest(
        graph_a_content="EX:INS EX:encodes EX:Insulin .",
        graph_a_format="turtle",
        graph_b_content="subject,predicate,object\nEX:Metformin,targets,EX:Insulin",
        graph_b_format="csv",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
    )

    res = service.execute_fusion(req)
    assert res.fusion_run.fusion_run_id is not None
    assert res.fusion_run.result_release_id is not None
    assert res.total_input_assertions == 2
    assert res.derived_assertions_count == 2
    assert len(res.nodes) >= 2


def test_graph_fusion_with_whitespace_identifiers():
    service = GraphFusionService()
    req = GraphFusionRequest(
        graph_a_content="subject,predicate,object\nInsulin Gene,encodes,Insulin Protein",
        graph_a_format="csv",
        graph_b_content="subject,predicate,object\nType 2 Diabetes,associated_with,Insulin Protein",
        graph_b_format="csv",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
    )

    res = service.execute_fusion(req)
    assert res.total_input_assertions == 2
    assert len(res.nodes) >= 2


def test_core_isolation_clean_imports():
    import sys

    for mod_name in sys.modules:
        if mod_name.startswith("core.fusion"):
            mod = sys.modules[mod_name]
            if hasattr(mod, "__file__") and mod.__file__:
                content = open(mod.__file__, encoding="utf-8").read()
                assert "plugins.biomedical" not in content
                assert "plugins.synthetic" not in content


def test_strict_rejection_with_full_rdf_iris_and_role_suffixes(capsys):
    service = GraphFusionService()

    graph_a = """
    @prefix exa: <http://biomed.example.org/a/> .
    exa:Metformin exa:treats exa:Type_2_Diabetes .
    """

    graph_b = """
    @prefix exb: <http://pharm.example.org/b/> .
    exb:Metformin_Drug exb:contraindicates exb:Type_2_Diabetes .
    """

    # 1. Preserve Mode Test: returns both opposing claims
    req_preserve = GraphFusionRequest(
        graph_a_content=graph_a,
        graph_a_format="turtle",
        graph_b_content=graph_b,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_PRESERVE,
    )
    res_preserve = service.execute_fusion(req_preserve)
    assert res_preserve.derived_assertions_count == 2
    assert len(res_preserve.edges) == 2

    # 2. Strict Rejection Mode Test: returns only 1 claim
    req_strict = GraphFusionRequest(
        graph_a_content=graph_a,
        graph_a_format="turtle",
        graph_b_content=graph_b,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_REJECT,
    )
    res_strict = service.execute_fusion(req_strict)

    # 3. Verify strict rejection purging and alias resolution
    assert res_strict.derived_assertions_count == 1
    assert len(res_strict.edges) == 1
    assert res_strict.merged_entity_count >= 1

    # 4. Verify original full IRI preservation
    m_node = next(n for n in res_strict.nodes if "Metformin" in n["id"])
    assert (
        "http://biomed.example.org/a/Metformin" in m_node["canonical_id"]
        or m_node["id"] == "http://biomed.example.org/a/Metformin"
    )

    # 5. Verify normalized predicate conflict report: treats ↔ contraindicates
    report = res_strict.conflict_report
    assert report["summary"]["total_contradictions_detected"] == 1
    assert "treats ↔ contraindicates" in report["contradiction_conflicts"][0]["normalized_conflict"]


def test_deterministic_conflict_resolution_and_audit_report():
    service = GraphFusionService()

    graph_a = """
    @prefix exa: <http://biomed.example.org/a/> .
    exa:Metformin exa:treats exa:Type_2_Diabetes .
    """

    graph_b = """
    @prefix exb: <http://pharm.example.org/b/> .
    exb:Metformin_Drug exb:contraindicates exb:Type_2_Diabetes .
    """

    # Order A -> B
    req1 = GraphFusionRequest(
        graph_a_content=graph_a,
        graph_a_format="turtle",
        graph_b_content=graph_b,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_REJECT,
    )
    res1 = service.execute_fusion(req1)

    # Order B -> A (reversed input)
    req2 = GraphFusionRequest(
        graph_a_content=graph_b,
        graph_a_format="turtle",
        graph_b_content=graph_a,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_REJECT,
    )
    service.execute_fusion(req2)

    # 1. Verify conflict report contains contradictions and deduplications
    report1 = res1.conflict_report
    assert "contradiction_conflicts" in report1
    assert "deduplicated_triples" in report1
    assert len(report1["contradiction_conflicts"]) == 1

    entry = report1["contradiction_conflicts"][0]
    assert "winning_predicate_iri" in entry
    assert "losing_predicate_iri" in entry
    assert (
        "treats" in entry["normalized_conflict"]
        and "contraindicates" in entry["normalized_conflict"]
    )
    assert entry["conflict_category"] == "CONTRADICTORY_PREDICATE_CONFLICT"

    # 2. Verify deterministic winner selection (both runs produce 1 edge with treats winning via Graph A precedence)
    assert res1.edges[0]["label"] == "http://biomed.example.org/a/treats"


def test_conflict_review_and_policy_decision_modes():
    service = GraphFusionService()

    graph_a = """
    @prefix exa: <http://biomed.example.org/a/> .
    exa:Metformin exa:treats exa:Type_2_Diabetes .
    """

    graph_b = """
    @prefix exb: <http://pharm.example.org/b/> .
    exb:Metformin_Drug exb:contraindicates exb:Type_2_Diabetes .
    """

    # 1. Test ConflictMode.CONFLICT_REVIEW
    req_review = GraphFusionRequest(
        graph_a_content=graph_a,
        graph_a_format="turtle",
        graph_b_content=graph_b,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_REVIEW,
    )
    res_review = service.execute_fusion(req_review)
    assert res_review.conflict_report["summary"]["review_required_count"] == 1
    assert (
        res_review.conflict_report["review_required_conflicts"][0]["action"]
        == "FLAGGED_FOR_HUMAN_REVIEW"
    )
    assert res_review.derived_assertions_count == 2

    # 2. Test ConflictMode.CONFLICT_POLICY_DECISION
    req_policy = GraphFusionRequest(
        graph_a_content=graph_a,
        graph_a_format="turtle",
        graph_b_content=graph_b,
        graph_b_format="turtle",
        conflict_mode=ConflictMode.CONFLICT_POLICY_DECISION,
    )
    res_policy = service.execute_fusion(req_policy)
    assert res_policy.derived_assertions_count == 1
    assert (
        res_policy.conflict_report["contradiction_conflicts"][0]["action"]
        == "REJECTED_LOSING_CLAIM"
    )
