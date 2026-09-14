"""Drug Repurposing Pilot Application (Phase 24).

Implements narrow drug repurposing workflow for a target disease using approved assertions.
Separates production, hypothesis, predicted, and rejected assertion layers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.assertion import Assertion
from core.identifiers.identifier import Identifier


class DrugRepurposingHypothesis(BaseModel):
    """A candidate drug repurposing hypothesis with full lineage and provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: Identifier
    drug_id: Identifier
    target_disease_id: Identifier
    mediating_protein_id: Identifier
    input_assertion_refs: tuple[Identifier, ...]
    evidence_refs: tuple[Identifier, ...] = Field(default_factory=tuple)
    derivation_method: str = Field(min_length=1)
    activity_id: Identifier
    agent_id: Identifier
    policy_id: str = Field(min_length=1)
    target_layer: str = Field(default="hypothesis", pattern="^hypothesis$")


class AssertionStoreLayers(BaseModel):
    """Segregated graph stores for different assertion lifecycle layers."""

    production: list[Assertion] = Field(default_factory=list)
    hypothesis: list[Assertion] = Field(default_factory=list)
    predicted: list[Assertion] = Field(default_factory=list)
    rejected: list[Assertion] = Field(default_factory=list)


class DrugRepurposingPipeline:
    """Executes drug repurposing graph traversal for a single target disease."""

    def __init__(self, agent_id: Identifier, activity_id: Identifier) -> None:
        self.agent_id = agent_id
        self.activity_id = activity_id

    def generate_hypotheses(
        self,
        *,
        target_disease_id: Identifier,
        layers: AssertionStoreLayers,
    ) -> list[DrugRepurposingHypothesis]:
        """Traverse approved production graph to generate repurposing hypotheses.

        Path: Disease <- associated_with <- Gene -> encodes -> Protein <- targets <- Drug
        """
        production_assertions = layers.production

        def _pred_matches(pred: str, target: str) -> bool:
            return pred == target or pred.endswith(f":{target}") or pred.endswith(f"/{target}")

        def _id_matches(id1: Identifier, id2: Identifier) -> bool:
            return id1 == id2 or (id1.value.lower() == id2.value.lower())

        # 1. Disease <- associated_with <- Gene
        disease_genes: dict[Identifier, Identifier] = {}
        for a in production_assertions:
            if _pred_matches(a.predicate, "associated_with") and _id_matches(
                a.object, target_disease_id
            ):
                disease_genes[a.subject] = a.id
            elif _pred_matches(a.predicate, "associated_with") and _id_matches(
                a.subject, target_disease_id
            ):
                disease_genes[a.object] = a.id

        # 2. Gene -> encodes -> Protein
        gene_proteins: dict[Identifier, tuple[Identifier, Identifier]] = {}
        for a in production_assertions:
            if _pred_matches(a.predicate, "encodes"):
                matched_gene = next((g for g in disease_genes if _id_matches(a.subject, g)), None)
                if matched_gene:
                    gene_proteins[a.object] = (matched_gene, a.id)

        # 3. Drug -> targets -> Protein
        hypotheses: list[DrugRepurposingHypothesis] = []
        for a in production_assertions:
            if _pred_matches(a.predicate, "targets"):
                matched_protein = next((p for p in gene_proteins if _id_matches(a.object, p)), None)
                if matched_protein:
                    drug_id = a.subject
                    protein_id = a.object
                    gene_id, encodes_assertion_id = gene_proteins[matched_protein]
                    assoc_assertion_id = disease_genes[gene_id]
                    targets_assertion_id = a.id

                    hyp_id = Identifier(
                        namespace="HYP",
                        value=f"REPURPOSE_{drug_id.value}_FOR_{target_disease_id.value}",
                    )

                    input_refs = (assoc_assertion_id, encodes_assertion_id, targets_assertion_id)

                    hyp = DrugRepurposingHypothesis(
                        hypothesis_id=hyp_id,
                        drug_id=drug_id,
                        target_disease_id=target_disease_id,
                        mediating_protein_id=protein_id,
                        input_assertion_refs=input_refs,
                        evidence_refs=(),
                        derivation_method="graph_repurposing_traversal_v1",
                        activity_id=self.activity_id,
                        agent_id=self.agent_id,
                        policy_id="repurposing_policy_v1",
                        target_layer="hypothesis",
                    )
                    hypotheses.append(hyp)

        return hypotheses
