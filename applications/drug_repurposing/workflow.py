"""Drug Repurposing Pilot Application (Phase 24).

Implements narrow drug repurposing workflow for a target disease using approved assertions.
Separates production, hypothesis, predicted, and rejected assertion layers.
"""

from __future__ import annotations

from typing import Any

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


def extract_detected_diseases(
    active_graph: dict[str, Any],
    assertion_store: Any = None,
) -> list[dict[str, Any]]:
    """Extract detected disease entities from active graph and assertion store."""
    detected_map: dict[str, dict[str, Any]] = {}

    # 1. Map associated_with edges in active graph
    disease_candidates_from_edges: set[str] = set()
    for edge in active_graph.get("edges", []):
        pred = str(edge.get("label", "")).lower()
        if "associated_with" in pred:
            to_val = str(edge.get("to", "")).strip()
            from_val = str(edge.get("from", "")).strip()
            if to_val:
                disease_candidates_from_edges.add(to_val)
            if from_val:
                disease_candidates_from_edges.add(from_val)

    # 2. Inspect active graph nodes
    for node in active_graph.get("nodes", []):
        n_id = str(node.get("id", "")).strip()
        n_label = str(node.get("label", "")).strip() or n_id
        n_canon = str(node.get("canonical_id", "")).strip()
        c_up = n_id.upper()

        is_disease = (
            n_id in disease_candidates_from_edges
            or any(c_up.startswith(p) for p in ("MONDO:", "DOID:", "EFO:", "HP:"))
            or any(
                term in n_label.lower()
                for term in (
                    "diabetes",
                    "cancer",
                    "malignancy",
                    "neoplasm",
                    "syndrome",
                    "disease",
                    "disorder",
                )
            )
        )
        if is_disease and n_id:
            detected_map[n_id] = {
                "id": n_id,
                "label": n_label,
                "canonical_id": n_canon or n_id,
                "source": "active_graph",
            }

    # 3. Inspect assertions in assertion_store as supplementary source
    if assertion_store is not None:
        try:
            if hasattr(assertion_store, "query_assertions"):
                matched_assertions = assertion_store.query_assertions("associated_with", limit=100)
            else:
                matched_assertions = []
            for a in matched_assertions:
                s_id = a.subject.canonical if hasattr(a.subject, "canonical") else str(a.subject)
                o_id = (
                    a.object.canonical
                    if hasattr(a, "object") and hasattr(a.object, "canonical")
                    else str(getattr(a, "object", ""))
                )
                for cand in (o_id, s_id):
                    c_up = cand.upper()
                    if any(c_up.startswith(p) for p in ("MONDO:", "DOID:", "EFO:", "HP:")):
                        if cand not in detected_map:
                            detected_map[cand] = {
                                "id": cand,
                                "label": cand,
                                "canonical_id": cand,
                                "source": "assertion_store",
                            }
        except Exception:
            pass

    return list(detected_map.values())


def run_drug_repurposing_pipeline(
    data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute drug repurposing pipeline from request payload and system context."""
    assertion_store = context.get("assertion_store")
    graph_store = context.get("graph_store")
    projection_store = context.get("projection_store")

    run_id = str(data.get("run_id", "run_web_001"))
    raw_disease = data.get("target_disease")
    if not raw_disease:
        # Dynamically discover in-graph disease candidates if none specified
        active_graph = (
            graph_store.get_active()
            if graph_store and hasattr(graph_store, "get_active")
            else {"nodes": [], "edges": []}
        )
        detected = extract_detected_diseases(active_graph, assertion_store)
        if detected:
            raw_disease = str(detected[0]["id"])
        else:
            raise ValueError(
                "Missing required 'target_disease' parameter and no candidate disease entities found in graph."
            )
    if ":" in raw_disease:
        ns, val = raw_disease.split(":", 1)
        disease_id = Identifier(namespace=ns, value=val)
    else:
        disease_id = Identifier(namespace="MONDO", value=raw_disease)

    pipeline = DrugRepurposingPipeline(
        agent_id=Identifier(namespace="SYS", value="AGENT_WEB"),
        activity_id=Identifier(namespace="SYS", value=f"ACT_REPURPOSE_{run_id}"),
    )

    prod_assertions: list[Assertion] = []
    release_id = data.get("release_id")
    if assertion_store:
        if release_id:
            prod_assertions = list(assertion_store.get_by_release(release_id))
        else:
            if projection_store:
                active_projections = projection_store.get_all_active()
                if active_projections:
                    for proj in active_projections:
                        fetched = list(assertion_store.get_by_release(proj.release_id))
                        if fetched:
                            prod_assertions.extend(fetched)
            if not prod_assertions and graph_store and hasattr(graph_store, "_session"):
                with graph_store._session() as conn:
                    rel_row = conn.execute(
                        "SELECT release_id FROM releases ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                    if rel_row:
                        prod_assertions = list(
                            assertion_store.get_by_release(rel_row["release_id"])
                        )
            if not prod_assertions and hasattr(assertion_store, "_session"):
                with assertion_store._session() as conn:
                    rows = conn.execute(
                        "SELECT * FROM assertions ORDER BY created_at ASC"
                    ).fetchall()
                    prod_assertions = [assertion_store._row_to_assertion(r) for r in rows]

    layers = AssertionStoreLayers(production=prod_assertions)
    hypotheses = pipeline.generate_hypotheses(target_disease_id=disease_id, layers=layers)

    return {
        "status": "success",
        "pipeline_type": "drug_repurposing",
        "target_disease": disease_id.canonical,
        "hypotheses_generated": len(hypotheses),
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
    }
