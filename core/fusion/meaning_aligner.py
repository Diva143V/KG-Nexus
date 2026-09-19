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

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.normalizer import NormalizedGraph, extract_local_name
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin
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
        self._class_map: dict[tuple[str, str], list[MeaningMapping]] = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.class_mappings
        )
        self._rel_map: dict[tuple[str, str], list[MeaningMapping]] = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.relation_mappings
        )
        self._attr_map: dict[tuple[str, str], list[MeaningMapping]] = self._build_mapping_lookup(
            self.domain_config.meaning_alignment.attribute_mappings
        )

    def _build_mapping_lookup(
        self, mappings: tuple[MeaningMapping, ...]
    ) -> dict[tuple[str, str], list[MeaningMapping]]:
        lookup: dict[tuple[str, str], list[MeaningMapping]] = defaultdict(list)
        for m in mappings:
            s_clean = extract_local_name(m.source_concept).lower()
            t_clean = extract_local_name(m.target_concept).lower()

            if m.direction in (MappingDirection.EQUIVALENT, MappingDirection.CANONICAL):
                # Normalize both sides using extract_local_name for consistent key format
                if m not in lookup[(s_clean, "graph_a")]:
                    lookup[(s_clean, "graph_a")].append(m)
                if m not in lookup[(s_clean, "graph_b")]:
                    lookup[(s_clean, "graph_b")].append(m)
                if m not in lookup[(t_clean, "graph_a")]:
                    lookup[(t_clean, "graph_a")].append(m)
                if m not in lookup[(t_clean, "graph_b")]:
                    lookup[(t_clean, "graph_b")].append(m)
            elif m.direction == MappingDirection.DIRECTED_A_TO_B:
                if m not in lookup[(s_clean, "graph_a")]:
                    lookup[(s_clean, "graph_a")].append(m)
            elif m.direction == MappingDirection.DIRECTED_B_TO_A:
                if m not in lookup[(s_clean, "graph_b")]:
                    lookup[(s_clean, "graph_b")].append(m)
        return dict(lookup)

    def align_predicate(
        self, predicate_str: str, from_graph: str = "graph_a"
    ) -> tuple[str, MeaningMapping | None]:
        """Align a relation predicate to its canonical target based on mapping direction."""
        p_local = extract_local_name(predicate_str).lower()
        fg = from_graph.lower()
        key = (p_local, fg)
        if key in self._rel_map and self._rel_map[key]:
            mapping = max(self._rel_map[key], key=lambda m: m.confidence)
            return mapping.target_concept, mapping

        # If from_graph is a custom identifier, check role-based fallback without violating directionality
        if fg not in ("graph_a", "graph_b"):
            is_a = (
                fg in ("a", "graph_a")
                or fg.endswith(("_a", ".a", ":a"))
                or fg.startswith(("a_", "a.", "a:"))
            )
            is_b = (
                fg in ("b", "graph_b")
                or fg.endswith(("_b", ".b", ":b"))
                or fg.startswith(("b_", "b.", "b:"))
            )
            if is_a and not is_b:
                if (p_local, "graph_a") in self._rel_map and self._rel_map[(p_local, "graph_a")]:
                    mapping = max(self._rel_map[(p_local, "graph_a")], key=lambda m: m.confidence)
                    return mapping.target_concept, mapping
            elif is_b and not is_a:
                if (p_local, "graph_b") in self._rel_map and self._rel_map[(p_local, "graph_b")]:
                    mapping = max(self._rel_map[(p_local, "graph_b")], key=lambda m: m.confidence)
                    return mapping.target_concept, mapping

        return predicate_str, None

    def align_attribute(
        self, attr_str: str, from_graph: str = "graph_a"
    ) -> tuple[str, MeaningMapping | None]:
        """Align a literal attribute property to its canonical target."""
        a_local = extract_local_name(attr_str).lower()
        fg = from_graph.lower()
        key = (a_local, fg)
        if key in self._attr_map and self._attr_map[key]:
            mapping = max(self._attr_map[key], key=lambda m: m.confidence)
            return mapping.target_concept, mapping

        # If from_graph is a custom identifier, check role-based fallback without violating directionality
        if fg not in ("graph_a", "graph_b"):
            is_a = (
                fg in ("a", "graph_a")
                or fg.endswith(("_a", ".a", ":a"))
                or fg.startswith(("a_", "a.", "a:"))
            )
            is_b = (
                fg in ("b", "graph_b")
                or fg.endswith(("_b", ".b", ":b"))
                or fg.startswith(("b_", "b.", "b:"))
            )
            if is_a and not is_b:
                if (a_local, "graph_a") in self._attr_map and self._attr_map[(a_local, "graph_a")]:
                    mapping = max(self._attr_map[(a_local, "graph_a")], key=lambda m: m.confidence)
                    return mapping.target_concept, mapping
            elif is_b and not is_a:
                if (a_local, "graph_b") in self._attr_map and self._attr_map[(a_local, "graph_b")]:
                    mapping = max(self._attr_map[(a_local, "graph_b")], key=lambda m: m.confidence)
                    return mapping.target_concept, mapping

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
        known_classes = {c for pair in disjoint_pairs for c in pair} | {
            et.name.lower() for et in self.domain_config.entity_types
        }

        def get_entity_type_names(ent: Any) -> set[str]:
            types = {str(ent.kind.value).lower()}
            if hasattr(ent, "label") and ent.label:
                lbl_lower = str(ent.label).lower()
                if lbl_lower in known_classes:
                    types.add(lbl_lower)
            val_parts = [str(getattr(ent.id, "value", "")).lower()]
            if hasattr(ent.id, "namespace") and ent.id.namespace:
                val_parts.append(str(ent.id.namespace).lower())
            if hasattr(ent.id, "canonical") and ent.id.canonical:
                val_parts.append(str(ent.id.canonical).lower())
            val_parts.append(str(ent.id).lower())
            val_lower = " ".join(val_parts)
            val_tokens = set(re.split(r"[/:\#_\-\s\.]+", val_lower))

            def _matches_token(name: str) -> bool:
                name_clean = name.rstrip("s")
                for tok in val_tokens:
                    if tok == name or tok.rstrip("s") == name_clean:
                        return True
                    if tok.endswith("ies") and tok[:-3] + "y" == name:
                        return True
                return False

            for et in self.domain_config.entity_types:
                et_name = et.name.lower()
                prefixes = {p.lower() for p in et.namespace_prefixes}
                if _matches_token(et_name) or any(_matches_token(p) for p in prefixes):
                    types.add(et_name)
            # Recognize ontology concepts declared in class mappings
            for m in self.domain_config.meaning_alignment.class_mappings:
                s_name = extract_local_name(m.source_concept).lower()
                t_name = extract_local_name(m.target_concept).lower()
                if _matches_token(s_name):
                    types.add(s_name)
                if _matches_token(t_name):
                    types.add(t_name)
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

            # Symmetric Class Mapping Validation:
            # Check both source entity types (Graph A) and candidate entity types (Graph B)
            # against the class mapping multimap, strictly respecting mapping directionality.
            s_norm_types = {
                extract_local_name(st).lower() if isinstance(st, str) else str(st).lower()
                for st in s_types
            }
            t_norm_types = {
                extract_local_name(tt).lower() if isinstance(tt, str) else str(tt).lower()
                for tt in t_types
            }

            cand_mappings_applied: list[str] = []

            # 1. Check mappings originating from Graph A (s_types)
            for st_norm in s_norm_types:
                class_key_a = (st_norm, "graph_a")
                for m in self._class_map.get(class_key_a, []):
                    s_clean = extract_local_name(m.source_concept).lower()
                    t_clean = extract_local_name(m.target_concept).lower()

                    if m.direction in (MappingDirection.EQUIVALENT, MappingDirection.CANONICAL):
                        expected_target = t_clean if st_norm == s_clean else s_clean
                        if expected_target in t_norm_types:
                            mapping_str = f"Class mapping: {m.source_concept} ↔ {m.target_concept}"
                            if mapping_str not in cand_mappings_applied:
                                cand_mappings_applied.append(mapping_str)
                                result.mappings_applied_count += 1
                    elif m.direction == MappingDirection.DIRECTED_A_TO_B:
                        if st_norm == s_clean and t_clean in t_norm_types:
                            mapping_str = f"Class mapping: {m.source_concept} ↔ {m.target_concept}"
                            if mapping_str not in cand_mappings_applied:
                                cand_mappings_applied.append(mapping_str)
                                result.mappings_applied_count += 1

            # 2. Check mappings originating from Graph B for DIRECTED_B_TO_A (t_types -> s_types)
            for tt_norm in t_norm_types:
                class_key_b = (tt_norm, "graph_b")
                for m in self._class_map.get(class_key_b, []):
                    if m.direction == MappingDirection.DIRECTED_B_TO_A:
                        s_clean = extract_local_name(m.source_concept).lower()
                        t_clean = extract_local_name(m.target_concept).lower()
                        if tt_norm == s_clean and t_clean in s_norm_types:
                            mapping_str = f"Class mapping: {m.source_concept} ↔ {m.target_concept}"
                            if mapping_str not in cand_mappings_applied:
                                cand_mappings_applied.append(mapping_str)
                                result.mappings_applied_count += 1

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
                derived_hash = hashlib.sha256(
                    f"{a.id.canonical}:{aligned_pred}:{a.subject.canonical}:{a.object.canonical}".encode()
                ).hexdigest()[:16]
                derived_id = Identifier(namespace="ASSERT", value=f"aligned_{derived_hash}")
                aligned_prov = a.provenance.model_copy(
                    update={
                        "assertion_origin": AssertionOrigin.DERIVED,
                        "input_assertion_refs": (a.id,),
                        "derivation_method": "meaning_alignment",
                    }
                )
                aligned_a = Assertion(
                    id=derived_id,
                    subject=a.subject,
                    predicate=aligned_pred,
                    object=a.object,
                    context=a.context,
                    confidence=a.confidence,
                    evidence=a.evidence,
                    provenance=aligned_prov,
                    status_at_creation=a.status_at_creation,
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
                derived_hash = hashlib.sha256(
                    f"{a.id.canonical}:{aligned_attr}:{a.subject.canonical}:{a.object.canonical}".encode()
                ).hexdigest()[:16]
                derived_id = Identifier(namespace="ASSERT", value=f"aligned_{derived_hash}")
                aligned_prov = a.provenance.model_copy(
                    update={
                        "assertion_origin": AssertionOrigin.DERIVED,
                        "input_assertion_refs": (a.id,),
                        "derivation_method": "meaning_alignment",
                    }
                )
                aligned_a = Assertion(
                    id=derived_id,
                    subject=a.subject,
                    predicate=aligned_attr,
                    object=a.object,
                    context=a.context,
                    confidence=a.confidence,
                    evidence=a.evidence,
                    provenance=aligned_prov,
                    status_at_creation=a.status_at_creation,
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
