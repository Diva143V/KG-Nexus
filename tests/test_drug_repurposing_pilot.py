"""Tests for Drug Repurposing Pilot Application (Phase 24)."""

from datetime import UTC, datetime

from applications.drug_repurposing.workflow import (
    AssertionStoreLayers,
    DrugRepurposingPipeline,
)
from core.assertions.assertion import Assertion
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance


def _make_assertion(a_id: str, subj: str, pred: str, obj: str) -> Assertion:
    prov = Provenance(
        agent_id=Identifier(namespace="SYS", value="agent_1"),
        activity_id=Identifier(namespace="SYS", value="act_1"),
        asserted_at=datetime.now(UTC),
    )
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="BIO", value=subj),
        predicate=pred,
        object=Identifier(namespace="BIO", value=obj),
        provenance=prov,
    )


def test_drug_repurposing_graph_traversal():
    disease_id = Identifier(namespace="BIO", value="DISEASE_T2D")
    gene_id = "GENE_INS"
    protein_id = "PROT_INS"
    drug_id = "DRUG_METFORMIN"

    # Create approved production graph assertions
    a1 = _make_assertion("a1", gene_id, "associated_with", "DISEASE_T2D")
    a2 = _make_assertion("a2", gene_id, "encodes", protein_id)
    a3 = _make_assertion("a3", drug_id, "targets", protein_id)

    layers = AssertionStoreLayers(production=[a1, a2, a3])

    agent_id = Identifier(namespace="SYS", value="AGENT_REPURPOSE")
    activity_id = Identifier(namespace="SYS", value="ACT_REPURPOSE_1")
    pipeline = DrugRepurposingPipeline(agent_id=agent_id, activity_id=activity_id)

    hypotheses = pipeline.generate_hypotheses(
        target_disease_id=disease_id,
        layers=layers,
    )

    assert len(hypotheses) == 1
    hyp = hypotheses[0]
    assert hyp.target_disease_id == disease_id
    assert hyp.drug_id.value == drug_id
    assert hyp.mediating_protein_id.value == protein_id
    assert len(hyp.input_assertion_refs) == 3
    assert hyp.target_layer == "hypothesis"  # Never promoted directly to production!
