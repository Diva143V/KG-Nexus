"""Tests for Biomedical Evidence Engine and Evidence Policies (Phase 20)."""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.evidence.evidence import Evidence
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from plugins.biomedical.evidence import (
    BiomedicalEvidenceEvaluator,
)


def _make_assertion_with_evidence(predicate: str, category_str: str) -> Assertion:
    prov = Provenance(
        agent_id=Identifier(namespace="SYS", value="agent_1"),
        activity_id=Identifier(namespace="SYS", value="act_1"),
        asserted_at=datetime.now(UTC),
    )
    ev = Evidence(
        id=Identifier(namespace="EV", value="ev_1"),
        record_id=Identifier(namespace="REC", value="rec_1"),
        detail={"category": category_str},
    )
    return Assertion(
        id=Identifier(namespace="ASSERT", value="assert_1"),
        subject=Identifier(namespace="CHEMBL", value="CHEMBL1431"),
        predicate=predicate,
        object=Identifier(namespace="MONDO", value="MONDO:0005148"),
        evidence=(ev,),
        provenance=prov,
    )


def test_positive_clinical_trial_evidence_promotion():
    evaluator = BiomedicalEvidenceEvaluator()
    assertion = _make_assertion_with_evidence("treats", "clinical_trial")

    decision = evaluator.evaluate(assertion)
    assert decision.promoted is True
    assert decision.target_layer == "production"


def test_negative_predicted_evidence_stored_in_hypothesis_layer():
    """PREDICTED evidence must never be silently promoted to production."""
    evaluator = BiomedicalEvidenceEvaluator()
    assertion = _make_assertion_with_evidence("treats", "predicted")

    decision = evaluator.evaluate(assertion)
    assert decision.promoted is False
    assert decision.target_layer == "hypothesis"
    assert "hypothesis" in decision.reason


def test_negative_insufficient_evidence_demoted_to_hypothesis():
    evaluator = BiomedicalEvidenceEvaluator()
    # 'treats' requires clinical_trial or expert_curated; observational is insufficient alone
    assertion = _make_assertion_with_evidence("treats", "observational")

    decision = evaluator.evaluate(assertion)
    assert decision.promoted is False
    assert decision.target_layer == "hypothesis"
