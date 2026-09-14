"""Stage 3: Meaning Aligner for Knowledge Graph Fusion.

Responsibilities:
- Directional and equivalence-aware Class, Relation, and Attribute mappings:
  - Class mapping: Type A <-> Type B
  - Relation mapping: relation A <-> relation B
  - Attribute mapping: name <-> fullName
- Disjoint class incompatibility checking (e.g. rejecting Person <-> Company matches)
- Canonicalization of relation predicates and literal attributes across input graphs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.normalizer import NormalizedGraph, extract_local_name
from sdk.domain_config import DomainFusionConfig, MappingDirection, MeaningMapping


@dataclass
class AlignedMeaningResult:
    """Result of Stage 3 Meaning Alignment."""

    aligned_candidates: list[EnhancedCandidateMatch] = field(default_factory=list)
    rejected_due_to_meaning: list[tuple[EnhancedCandidateMatch, str]] = field(default_factory=list)
    mappings_applied_count: int = 0
    mappings_applied_log: list[dict[str, Any]] = field(default_factory=list)
    ontology_shortages: list[dict[str, Any]] = field(default_factory=list)


class MeaningAligner:
    """Executes Stage 3: Meaning Alignment."""

    def __init__(self, domain_config: DomainFusionConfig) -> None:
        self.domain_config = domain_config
        self._class_map = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.class_mappings
        )
        self._rel_map = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.relation_mappings
        )
        self._attr_map = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.attribute_mappings
        )

    def _build_mapping_lookup(
        self, mappings: tuple[MeaningMapping, ...]
    ) -> dict[tuple[str, str], MeaningMapping]:
        lookup: dict[tuple[str, str], MeaningMapping] = {}
        for m in mappings:
            s_clean = extract_local_name(m.source_concept).lower()
            t_clean = extract_local_name(m.target_concept).lower()

            if m.direction in (MappingDirection.EQUIVALENT, MappingDirection.CANONICAL):
                # Normalize both sides using extract_local_name for consistent key format
                lookup[(s_clean, "graph_a")] = m
                lookup[(s_clean, "graph_b")] = m
                lookup[(t_clean, "graph_a")] = m
                lookup[(t_clean, "graph_b")] = m
            elif m.direction == MappingDirection.DIRECTED_A_TO_B:
                lookup[(s_clean, "graph_a")] = m
            elif m.direction == MappingDirection.DIRECTED_B_TO_A:
                lookup[(s_clean, "graph_b")] = m
        return lookup

    def align_predicate(
        self, predicate_str: str, from_graph: str = "graph_a"
    ) -> tuple[str, MeaningMapping | None]:
        """Align a relation predicate to its canonical target based on mapping direction."""
        p_local = extract_local_name(predicate_str).lower()
        fg = from_graph.lower()
        key = (p_local, fg)
        if key in self._rel_map:
            mapping = self._rel_map[key]
            return mapping.target_concept, mapping

        # If from_graph is a custom identifier, check role-based fallback without violating directionality
        if fg not in ("graph_a", "graph_b"):
            if "a" in fg and (p_local, "graph_a") in self._rel_map:
                return self._rel_map[(p_local, "graph_a")].target_concept, self._rel_map[
                    (p_local, "graph_a")
                ]
            if "b" in fg and (p_local, "graph_b") in self._rel_map:
                return self._rel_map[(p_local, "graph_b")].target_concept, self._rel_map[
                    (p_local, "graph_b")
                ]

        return predicate_str, None

    def align_attribute(
        self, attr_str: str, from_graph: str = "graph_a"
    ) -> tuple[str, MeaningMapping | None]:
        """Align a literal attribute property to its canonical target."""
        a_local = extract_local_name(attr_str).lower()
        fg = from_graph.lower()
        key = (a_local, fg)
        if key in self._attr_map:
            mapping = self._attr_map[key]
            return mapping.target_concept, mapping

        # If from_graph is a custom identifier, check role-based fallback without violating directionality
        if fg not in ("graph_a", "graph_b"):
            if "a" in fg and (a_local, "graph_a") in self._attr_map:
                return self._attr_map[(a_local, "graph_a")].target_concept, self._attr_map[
                    (a_local, "graph_a")
                ]
            if "b" in fg and (a_local, "graph_b") in self._attr_map:
                return self._attr_map[(a_local, "graph_b")].target_concept, self._attr_map[
                    (a_local, "graph_b")
                ]

        return attr_str, None

    def align_candidates(
        self,
        candidates: list[EnhancedCandidateMatch],
        graph_a: NormalizedGraph,
        graph_b: NormalizedGraph,
    ) -> AlignedMeaningResult:
        """Align and validate candidate matches according to ontology & class semantics."""
        result = AlignedMeaningResult()
        disjoint_pairs = {
            (d[0].lower(), d[1].lower())
            for d in self.domain_config.meaning_alignment.disjoint_classes
        }
        disjoint_pairs.update(
            {
                (d[1].lower(), d[0].lower())
                for d in self.domain_config.meaning_alignment.disjoint_classes
            }
        )

        def get_entity_type_names(ent: Any) -> set[str]:
            types = {str(ent.kind.value).lower()}
            if hasattr(ent, "label") and ent.label:
                types.add(str(ent.label).lower())
            val_lower = str(ent.id.value).lower()
            for et in self.domain_config.entity_types:
                if et.name.lower() in val_lower or any(
                    p.lower() in val_lower for p in et.namespace_prefixes
                ):
                    types.add(et.name.lower())
            return types

        for cand in candidates:
            s_id = str(cand.source_entity.id.value)
            t_id = str(cand.candidate_entity.id.value)

            # Check kind mismatch or disjoint classes
            s_types = get_entity_type_names(cand.source_entity)
            t_types = get_entity_type_names(cand.candidate_entity)

            is_disjoint = False
            disjoint_match_str = ""
            for st in s_types:
                for tt in t_types:
                    if (st, tt) in disjoint_pairs:
                        is_disjoint = True
                        disjoint_match_str = f"{st} and {tt}"
                        break
                if is_disjoint:
                    break

            if is_disjoint:
                reason = f"Disjoint class mismatch: {disjoint_match_str} are mutually exclusive in ontology"
                result.rejected_due_to_meaning.append((cand, reason))
                continue

            # Check if class mapping applies
            # Note: Mapping lookup keys are built as (concept_name_lower, "graph_a" | "graph_b")
            # using extract_local_name for consistent key format
            cand_mappings_applied: list[str] = []
            for st in s_types:
                # Normalize st using extract_local_name to match mapping key format
                st_normalized = (
                    extract_local_name(st).lower() if isinstance(st, str) else str(st).lower()
                )
                # Check both graph_a and graph_b keys for EQUIVALENT mappings
                class_key_a = (st_normalized, "graph_a")
                class_key_b = (st_normalized, "graph_b")
                if class_key_a in self._class_map:
                    m = self._class_map[class_key_a]
                    cand_mappings_applied.append(
                        f"Class mapping: {m.source_concept} ↔ {m.target_concept}"
                    )
                    result.mappings_applied_count += 1
                    break
                elif class_key_b in self._class_map:
                    m = self._class_map[class_key_b]
                    cand_mappings_applied.append(
                        f"Class mapping: {m.source_concept} ↔ {m.target_concept}"
                    )
                    result.mappings_applied_count += 1
                    break

            if cand_mappings_applied:
                if hasattr(cand, "evidence") and isinstance(cand.evidence, list):
                    cand.evidence.extend(cand_mappings_applied)
                result.mappings_applied_log.append(
                    {
                        "source_id": s_id,
                        "target_id": t_id,
                        "mappings": cand_mappings_applied,
                    }
                )

            result.aligned_candidates.append(cand)

        return result

    def align_assertions(
        self,
        graph: NormalizedGraph,
        graph_name: str,
        result: AlignedMeaningResult | None = None,
    ) -> list[Assertion]:
        """Align predicates and attributes across relational and literal assertions."""
        aligned_assertions: list[Assertion] = []

        # 1. Align relational assertions
        for a in graph.relational_assertions:
            pred_str = str(a.predicate)
            aligned_pred, mapping = self.align_predicate(pred_str, from_graph=graph_name)
            if mapping is not None:
                aligned_a = Assertion(
                    id=a.id,
                    subject=a.subject,
                    predicate=aligned_pred,
                    object=a.object,
                    provenance=a.provenance,
                )
                aligned_assertions.append(aligned_a)
                if result is not None:
                    result.mappings_applied_count += 1
            else:
                p_local = extract_local_name(pred_str)
                std_namespaces = self.domain_config.meaning_alignment.standard_ontology_namespaces
                is_standard = any(std.lower() in pred_str.lower() for std in std_namespaces)
                if not is_standard and result is not None:
                    shortage_record = {
                        "unmapped_predicate": pred_str,
                        "local_name": p_local,
                        "source_graph": graph_name,
                        "status": "ONTOLOGY_SHORTAGE_DETECTED",
                        "fallback_iri": self.domain_config.meaning_alignment.ontology_shortage_fallback_iri,
                        "action": "PRESERVED_WITH_SHORTAGE_WARNING",
                        "recommendation": f"Add MeaningMapping for '{p_local}' in domain_config",
                    }
                    if not any(
                        s["unmapped_predicate"] == pred_str and s["source_graph"] == graph_name
                        for s in result.ontology_shortages
                    ):
                        result.ontology_shortages.append(shortage_record)
                aligned_assertions.append(a)

        # 2. Align literal assertions (Attribute Alignment)
        for a in graph.literal_assertions:
            attr_str = str(a.predicate)
            aligned_attr, mapping = self.align_attribute(attr_str, from_graph=graph_name)
            if mapping is not None:
                aligned_a = Assertion(
                    id=a.id,
                    subject=a.subject,
                    predicate=aligned_attr,
                    object=a.object,
                    provenance=a.provenance,
                )
                aligned_assertions.append(aligned_a)
                if result is not None:
                    result.mappings_applied_count += 1
            else:
                if result is not None:
                    a_local = extract_local_name(attr_str)
                    std_namespaces = (
                        self.domain_config.meaning_alignment.standard_ontology_namespaces
                    )
                    is_standard = any(std.lower() in attr_str.lower() for std in std_namespaces)
                    if not is_standard:
                        shortage_record = {
                            "unmapped_predicate": attr_str,
                            "local_name": a_local,
                            "source_graph": graph_name,
                            "status": "ONTOLOGY_SHORTAGE_DETECTED",
                            "fallback_iri": self.domain_config.meaning_alignment.ontology_shortage_fallback_iri,
                            "action": "PRESERVED_WITH_SHORTAGE_WARNING",
                            "recommendation": f"Add MeaningMapping for '{a_local}' in domain_config",
                        }
                        if not any(
                            s["unmapped_predicate"] == attr_str and s["source_graph"] == graph_name
                            for s in result.ontology_shortages
                        ):
                            result.ontology_shortages.append(shortage_record)
                aligned_assertions.append(a)

        return aligned_assertions
