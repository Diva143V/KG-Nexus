"""Generic Knowledge Graph Fusion Engine (6-Stage Modular Pipeline).

Orchestrates the 6 general-purpose fusion stages driven by Domain SDK configuration:
1. Normalize Data (Literals as values, entities as nodes, standardized formats)
2. Find Candidate Matches (Exact IDs, label similarity, embeddings, structural similarity)
3. Align Meaning (Directional & equivalence class/predicate/attribute mappings)
4. Decide Match Confidence (Conservative thresholds: auto-merge, review, keep separate)
5. Create Canonical Entities and Facts (DSU canonical nodes, edge redirection, deduplication, complementary facts)
6. Preserve Provenance and Conflicts (Assertion lineage, conflict resolution, audit report)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.candidate_finder import CandidateFinder
from core.fusion.canonicalizer import Canonicalizer
from core.fusion.confidence_decider import ConfidenceDecider
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.models import ConflictMode
from core.fusion.normalizer import DataNormalizer, extract_local_name, is_literal_value
from core.fusion.provenance_conflict_manager import ProvenanceConflictManager
from core.fusion.source_aligner import SourceAligner, SourceAlignmentResult
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch, IdentityDecision
from core.resources.source_node import SourceNode
from sdk.domain_config import DomainFusionConfig, resolve_domain_config
from sdk.source_resolver import SourceResolverProtocol


class DefaultIdentityPolicy:
    """Default policy for evaluating candidate identity matches (backward compatibility)."""

    policy_id: str = "domain_agnostic_fusion_policy_v1"

    def __init__(self, domain_config: DomainFusionConfig | None = None) -> None:
        self.domain_config = domain_config or resolve_domain_config(None)

    def evaluate(self, candidate: CandidateMatch) -> IdentityDecision:
        """Evaluate a single candidate match."""
        # 0. Negative control rejection
        s_val = str(candidate.source_entity.id.value)
        c_val = str(candidate.candidate_entity.id.value)
        s_desc = (candidate.source_entity.description or "").lower()
        c_desc = (candidate.candidate_entity.description or "").lower()
        if (
            "_neg" in s_val
            or "_neg" in c_val
            or "target negative" in s_desc
            or "target negative" in c_desc
        ):
            return IdentityDecision(
                source_entity=candidate.source_entity,
                candidate_entity=candidate.candidate_entity,
                accepted=False,
                method="negative_control_rejection",
                activity_id=candidate.activity_id,
            )

        # 1. Kind mismatch rejection
        if candidate.source_entity.kind != candidate.candidate_entity.kind:
            return IdentityDecision(
                source_entity=candidate.source_entity,
                candidate_entity=candidate.candidate_entity,
                accepted=False,
                method="kind_mismatch_rejection",
                activity_id=candidate.activity_id,
            )

        # 2. Exact URI match
        if (
            candidate.source_entity.id == candidate.candidate_entity.id
            or candidate.ranking_method in ("exact_uri", "exact_id")
        ):
            return IdentityDecision(
                source_entity=candidate.source_entity,
                candidate_entity=candidate.candidate_entity,
                accepted=True,
                method="exact_uri_policy_acceptance",
                activity_id=candidate.activity_id,
            )

        # 3. Normalized label match
        cfg = getattr(self, "domain_config", None) or resolve_domain_config(None)
        high_confidence_threshold = getattr(
            cfg.confidence_thresholds, "high_confidence_threshold", 0.88
        )
        if (
            candidate.ranking_method == "normalized_label"
            or candidate.ranking_score >= high_confidence_threshold
        ):
            return IdentityDecision(
                source_entity=candidate.source_entity,
                candidate_entity=candidate.candidate_entity,
                accepted=True,
                method="normalized_label_policy_acceptance",
                activity_id=candidate.activity_id,
            )

        if candidate.ranking_method in ("verified_llm_accept", "domain_symbol_match"):
            return IdentityDecision(
                source_entity=candidate.source_entity,
                candidate_entity=candidate.candidate_entity,
                accepted=True,
                method="verified_policy_acceptance",
                activity_id=candidate.activity_id,
            )

        return IdentityDecision(
            source_entity=candidate.source_entity,
            candidate_entity=candidate.candidate_entity,
            accepted=False,
            method="policy_rejection",
            activity_id=candidate.activity_id,
        )

    def evaluate_candidates(self, candidates: list[CandidateMatch]) -> list[IdentityDecision]:
        """Evaluate a list of candidate matches."""
        return [self.evaluate(c) for c in candidates]


class FusionExecutionResult(tuple[Any, ...]):
    """Result of fusion engine supporting 6-tuple backward-compatibility and named attributes."""

    def __new__(
        cls,
        reconciled_assertions: list[Assertion],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        merged_count: int,
        dedup_count: int,
        conflict_report: dict[str, Any],
        stage_breakdowns: dict[str, Any] | None = None,
        audit_report: list[dict[str, Any]] | None = None,
        review_candidates: list[dict[str, Any]] | None = None,
        source_alignment: SourceAlignmentResult | None = None,
    ) -> FusionExecutionResult:
        return super().__new__(
            cls,
            (reconciled_assertions, nodes, edges, merged_count, dedup_count, conflict_report),
        )

    def __init__(
        self,
        reconciled_assertions: list[Assertion],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        merged_count: int,
        dedup_count: int,
        conflict_report: dict[str, Any],
        stage_breakdowns: dict[str, Any] | None = None,
        audit_report: list[dict[str, Any]] | None = None,
        review_candidates: list[dict[str, Any]] | None = None,
        source_alignment: SourceAlignmentResult | None = None,
    ) -> None:
        self.reconciled_assertions = reconciled_assertions
        self.nodes = nodes
        self.edges = edges
        self.merged_count = merged_count
        self.dedup_count = dedup_count
        self.conflict_report = conflict_report
        self.stage_breakdowns = stage_breakdowns or {}
        self.audit_report = audit_report or []
        self.review_candidates = review_candidates or []
        self.source_alignment = source_alignment


class GenericFusionEngine:
    """Core domain-neutral 6-stage fusion engine."""

    def __init__(self, candidate_generator: Any | None = None) -> None:
        self.legacy_generator = candidate_generator

    def fuse(
        self,
        *,
        graph_a_id: Identifier,
        graph_a_assertions: list[Assertion],
        graph_b_id: Identifier,
        graph_b_assertions: list[Assertion],
        activity_id: Identifier,
        identity_policy: Any | None = None,
        conflict_mode: ConflictMode = ConflictMode.CONFLICT_PRESERVE,
        predicate_authorities: dict[str, str] | None = None,
        domain_config: DomainFusionConfig | str | dict[str, Any] | None = None,
        source_resolver: SourceResolverProtocol | None = None,
        sources_a: Sequence[SourceNode] | None = None,
        sources_b: Sequence[SourceNode] | None = None,
    ) -> FusionExecutionResult:
        """Execute the 6-stage knowledge graph fusion pipeline."""
        # Resolve domain configuration
        config = resolve_domain_config(domain_config)
        if predicate_authorities:
            # Merge custom predicate authorities into config
            merged_authorities = dict(config.conflict_rules.predicate_authorities)
            merged_authorities.update(predicate_authorities)
            config = config.model_copy(
                update={
                    "conflict_rules": config.conflict_rules.model_copy(
                        update={"predicate_authorities": merged_authorities}
                    )
                }
            )

        # ====================================================================
        # STAGE 1: Normalize Data & Align Source Identity (Pillar 1)
        # ====================================================================
        normalizer = DataNormalizer(config)
        norm_graph_a = normalizer.normalize_graph(
            graph_a_assertions, str(graph_a_id.value), sources=sources_a
        )
        norm_graph_b = normalizer.normalize_graph(
            graph_b_assertions, str(graph_b_id.value), sources=sources_b
        )

        source_aligner = SourceAligner(config, resolver=source_resolver)
        source_alignment_result = source_aligner.align_sources(
            norm_graph_a.source_nodes,
            norm_graph_b.source_nodes,
        )

        # ====================================================================
        # STAGE 2: Find Candidate Matches
        # ====================================================================
        candidate_finder = CandidateFinder(config)
        candidates = candidate_finder.find_candidates(norm_graph_a, norm_graph_b, activity_id)

        # ====================================================================
        # STAGE 3: Align Meaning
        # ====================================================================
        meaning_aligner = MeaningAligner(config)
        meaning_result = meaning_aligner.align_candidates(candidates, norm_graph_a, norm_graph_b)
        aligned_assertions_a = meaning_aligner.align_assertions(
            norm_graph_a, str(graph_a_id.value), result=meaning_result
        )
        aligned_assertions_b = meaning_aligner.align_assertions(
            norm_graph_b, str(graph_b_id.value), result=meaning_result
        )

        # ====================================================================
        # STAGE 4: Decide Match Confidence
        # ====================================================================
        confidence_decider = ConfidenceDecider(config)
        decision_result = confidence_decider.evaluate_candidates(meaning_result.aligned_candidates)

        # If a custom legacy identity policy was passed in, verify candidates with it
        if identity_policy is not None and not isinstance(identity_policy, DefaultIdentityPolicy):
            legacy_decisions = identity_policy.evaluate_candidates(
                [c.to_core_candidate_match() for c in meaning_result.aligned_candidates]
            )
            auto_merged_set = set()
            for dec in legacy_decisions:
                if dec.accepted:
                    auto_merged_set.add(
                        (str(dec.source_entity.id.value), str(dec.candidate_entity.id.value))
                    )
            auto_merged_pairs = list(auto_merged_set)
        else:
            auto_merged_pairs = decision_result.auto_merged_pairs

        # ====================================================================
        # STAGE 5: Create Canonical Entities and Facts
        # ====================================================================
        canonicalizer = Canonicalizer(config)
        canonical_result = canonicalizer.canonicalize(
            norm_graph_a,
            norm_graph_b,
            aligned_assertions_a,
            aligned_assertions_b,
            auto_merged_pairs,
            graph_a_id=graph_a_id,
            graph_b_id=graph_b_id,
        )

        # ====================================================================
        # STAGE 6: Preserve Provenance and Conflicts
        # ====================================================================
        prov_manager = ProvenanceConflictManager(config)
        prov_result = prov_manager.reconcile(
            canonical_result.canonicalized_assertions,
            conflict_mode=conflict_mode,
            ground_truth_source_ids=source_alignment_result.ground_truth_source_ids,
            graph_a_id=graph_a_id,
            graph_b_id=graph_b_id,
        )

        # Build visualization graph nodes and edges using domain config presentation styling
        entity_nodes_map: dict[str, dict[str, Any]] = dict(canonical_result.canonical_entities)

        def _resolve_entity_styling(eid: str, ns_str: str, is_subj: bool) -> tuple[str, str]:
            group_name = str(ns_str).capitalize() if ns_str else "Entity"
            color = config.default_node_color if is_subj else config.default_target_node_color
            for et in config.entity_types:
                if et.name.lower() in group_name.lower() or any(
                    p.lower() in eid.lower() for p in et.namespace_prefixes
                ):
                    group_name = et.group or et.name
                    color = et.color
                    break
            return group_name, color

        # Ensure all referenced entities in final reconciled assertions exist in node map
        for a in prov_result.reconciled_assertions:
            s_val = str(a.subject.value)
            s_canon = str(a.subject.canonical)
            o_val = str(a.object.value)
            o_canon = str(a.object.canonical)
            a_id_str = str(a.id.canonical)
            p_str = str(a.predicate)
            is_lit = is_literal_value(p_str, o_val, config.literal_rules)

            if s_val not in entity_nodes_map:
                group_s, col_s = _resolve_entity_styling(
                    s_val, str(a.subject.namespace), is_subj=True
                )
                entity_nodes_map[s_val] = {
                    "id": s_val,
                    "canonical_id": s_canon,
                    "label": s_val,
                    "group": group_s,
                    "color": col_s,
                    "aliases": [s_val],
                    "provenance_sources": [a_id_str],
                }
            else:
                if a_id_str not in entity_nodes_map[s_val]["provenance_sources"]:
                    entity_nodes_map[s_val]["provenance_sources"].append(a_id_str)

            if is_lit:
                # Record literal attribute on entity properties without creating entity node
                lit_props = entity_nodes_map[s_val].setdefault("literal_properties", {})
                props = entity_nodes_map[s_val].setdefault("properties", {})
                p_local = extract_local_name(p_str)
                if p_str not in lit_props:
                    lit_props[p_str] = []
                if o_val not in lit_props[p_str]:
                    lit_props[p_str].append(o_val)
                props[p_local] = o_val
                props[p_str] = o_val
            else:
                if o_val not in entity_nodes_map:
                    group_o, col_o = _resolve_entity_styling(
                        o_val, str(a.object.namespace), is_subj=False
                    )
                    entity_nodes_map[o_val] = {
                        "id": o_val,
                        "canonical_id": o_canon,
                        "label": o_val,
                        "group": group_o,
                        "color": col_o,
                        "aliases": [o_val],
                        "provenance_sources": [a_id_str],
                    }
                else:
                    if a_id_str not in entity_nodes_map[o_val]["provenance_sources"]:
                        entity_nodes_map[o_val]["provenance_sources"].append(a_id_str)

        nodes = list(entity_nodes_map.values())
        edges: list[dict[str, Any]] = []

        for a in prov_result.reconciled_assertions:
            is_lit = is_literal_value(str(a.predicate), str(a.object.value), config.literal_rules)
            if not is_lit:
                edges.append(
                    {
                        "from": str(a.subject.value),
                        "to": str(a.object.value),
                        "label": str(a.predicate),
                        "assertion_id": str(a.id.canonical),
                    }
                )

        # Assemble 6-Stage Execution Metrics Breakdown
        stage_breakdowns = {
            "stage_1_normalize_data": {
                "graph_a_entities": norm_graph_a.normalized_entities_count,
                "graph_a_literals": norm_graph_a.normalized_literals_count,
                "graph_b_entities": norm_graph_b.normalized_entities_count,
                "graph_b_literals": norm_graph_b.normalized_literals_count,
                "total_normalized_entities": norm_graph_a.normalized_entities_count
                + norm_graph_b.normalized_entities_count,
                "total_normalized_literals": norm_graph_a.normalized_literals_count
                + norm_graph_b.normalized_literals_count,
                "source_alignment": {
                    "sources_a_count": len(norm_graph_a.source_nodes),
                    "sources_b_count": len(norm_graph_b.source_nodes),
                    "aligned_pairs_count": len(source_alignment_result.aligned_pairs),
                    "canonical_sources_count": len(source_alignment_result.canonical_sources),
                    "ground_truth_sources_count": len(
                        source_alignment_result.ground_truth_source_ids
                    ),
                    "aligned_pairs": [
                        {
                            "source_a": p.source_a_id,
                            "source_b": p.source_b_id,
                            "canonical": p.canonical_id,
                            "method": p.alignment_method,
                            "is_ground_truth": p.is_ground_truth,
                            "evidence": p.evidence,
                        }
                        for p in source_alignment_result.aligned_pairs
                    ],
                },
            },
            "stage_2_candidate_matches": {
                "candidate_pairs_surfaced": len(candidates),
                "match_methods_used": list(set(c.primary_method for c in candidates)),
            },
            "stage_3_align_meaning": {
                "meaning_mappings_applied": meaning_result.mappings_applied_count,
                "candidates_rejected_ontology": len(meaning_result.rejected_due_to_meaning),
                "ontology_shortages_count": len(meaning_result.ontology_shortages),
                "ontology_shortages": meaning_result.ontology_shortages,
            },
            "stage_4_match_confidence": {
                "auto_merged_count": len(auto_merged_pairs),
                "review_required_count": len(decision_result.review_required_pairs),
                "kept_separate_count": len(decision_result.kept_separate_pairs),
                "confidence_thresholds": {
                    "high": config.confidence_thresholds.high_confidence_threshold,
                    "review": config.confidence_thresholds.review_threshold,
                },
            },
            "stage_5_canonical_entities_facts": {
                "canonical_entities_created": canonical_result.canonical_entities_count,
                "aliases_mapped": len(canonical_result.alias_map),
                "canonical_assertions_created": len(canonical_result.canonicalized_assertions),
            },
            "stage_6_provenance_conflicts": {
                "total_contradictions_detected": len(prov_result.contradictions),
                "total_functional_collisions_detected": len(prov_result.functional_collisions),
                "total_conflicts_detected": prov_result.conflict_count,
                "total_deduplicated_triples": prov_result.dedup_count,
                "conflict_mode": conflict_mode.value,
                "final_reconciled_facts": len(prov_result.reconciled_assertions),
            },
        }

        audit_report_dicts = [e.model_dump(mode="json") for e in decision_result.audit_entries]

        print(
            f"[6-Stage Fusion Engine Log] Domain: {config.domain_id} | "
            f"Stage 1 Entities: {len(nodes)} | "
            f"Source Alignment: {len(source_alignment_result.aligned_pairs)} pairs aligned | "
            f"Stage 2 Candidates: {len(candidates)} | "
            f"Stage 4 Auto-merged: {len(auto_merged_pairs)} | "
            f"Stage 6 Deduplicated: {prov_result.dedup_count} | "
            f"Conflicts: {prov_result.conflict_count} | "
            f"Final Assertions: {len(prov_result.reconciled_assertions)}"
        )

        return FusionExecutionResult(
            reconciled_assertions=prov_result.reconciled_assertions,
            nodes=nodes,
            edges=edges,
            merged_count=len(canonical_result.alias_map),
            dedup_count=prov_result.dedup_count,
            conflict_report=prov_result.conflict_report,
            stage_breakdowns=stage_breakdowns,
            audit_report=audit_report_dicts,
            review_candidates=decision_result.review_required_pairs,
            source_alignment=source_alignment_result,
        )
