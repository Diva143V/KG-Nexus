"""Stage 5: Canonical Entities and Facts Creator for Knowledge Graph Fusion.

Responsibilities:
- Build single canonical entity nodes for each matched entity cluster (via Disjoint Set Union).
- Preserve all original IDs as aliases and provenance sources on canonical entities.
- Redirect all source edges (subject and object) to canonical nodes.
- Deduplicate equivalent facts (identical canonical subject, predicate, object) while aggregating provenance.
- Preserve complementary facts (distinct attributes and relations from both graphs are retained).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.evidence.evidence import Evidence
from core.fusion.normalizer import (
    NormalizedGraph,
    extract_local_name,
    is_literal_value,
    normalize_literal_format,
)
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from sdk.domain_config import DomainFusionConfig


class DisjointSetUnion:
    """Disjoint Set Union (DSU) for transitive entity cluster canonicalization."""

    def __init__(
        self,
        preferred_entities: set[str] | None = None,
        secondary_entities: set[str] | None = None,
    ) -> None:
        self.parent: dict[str, str] = {}
        self.preferred_entities: set[str] = preferred_entities or set()
        self.secondary_entities: set[str] = secondary_entities or set()

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1: str, item2: str) -> None:
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            # Deterministic ordering based on explicit graph precedence configuration
            is_pref1 = root1 in self.preferred_entities
            is_pref2 = root2 in self.preferred_entities
            is_sec1 = root1 in self.secondary_entities
            is_sec2 = root2 in self.secondary_entities

            if is_pref1 and not is_pref2:
                self.parent[root2] = root1
            elif is_pref2 and not is_pref1:
                self.parent[root1] = root2
            elif is_sec2 and not is_sec1:
                self.parent[root2] = root1
            elif is_sec1 and not is_sec2:
                self.parent[root1] = root2
            else:
                # Fallback to deterministic lexicographic tie-breaker
                if root1 <= root2:
                    self.parent[root2] = root1
                else:
                    self.parent[root1] = root2


@dataclass
class CanonicalGraphResult:
    """Result of Stage 5 Canonicalization."""

    canonical_entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    canonicalized_assertions: list[Assertion] = field(default_factory=list)
    alias_map: dict[str, str] = field(default_factory=dict)
    deduplicated_facts_count: int = 0
    complementary_facts_count: int = 0
    canonical_entities_count: int = 0


class Canonicalizer:
    """Executes Stage 5: Canonical Entities and Facts Synthesis."""

    def __init__(self, domain_config: DomainFusionConfig) -> None:
        self.domain_config = domain_config

    def canonicalize(
        self,
        graph_a: NormalizedGraph,
        graph_b: NormalizedGraph,
        aligned_assertions_a: list[Assertion],
        aligned_assertions_b: list[Assertion],
        auto_merged_pairs: list[tuple[str, str]],
        *,
        graph_a_id: Identifier | str | None = None,
        graph_b_id: Identifier | str | None = None,
    ) -> CanonicalGraphResult:
        """Create canonical entities, redirect edges, deduplicate equivalent facts, preserve complementary facts."""
        result = CanonicalGraphResult()

        prec = self.domain_config.conflict_rules.default_graph_precedence.lower()
        if prec == "graph_b":
            preferred = set(graph_b.entities.keys())
            secondary = set(graph_a.entities.keys())
        else:
            preferred = set(graph_a.entities.keys())
            secondary = set(graph_b.entities.keys())

        dsu = DisjointSetUnion(preferred_entities=preferred, secondary_entities=secondary)

        # Initialize all entities in DSU
        all_entities = {**graph_a.entities, **graph_b.entities}
        for eid in all_entities:
            dsu.find(eid)

        # Union all auto-merged pairs
        for s_id, t_id in auto_merged_pairs:
            dsu.union(s_id, t_id)

        # Build alias map: original_id -> canonical_id
        alias_map: dict[str, str] = {}
        for eid in all_entities:
            root = dsu.find(eid)
            if root != eid:
                alias_map[eid] = root
        result.alias_map = alias_map

        # Build canonical entity nodes with full alias & provenance preservation
        clusters: dict[str, list[str]] = {}
        for eid in all_entities:
            root = dsu.find(eid)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(eid)

        for canon_id, members in clusters.items():
            if canon_id in all_entities:
                primary_ent = all_entities[canon_id]
            else:
                available = [m for m in members if m in all_entities]
                if available:
                    primary_ent = all_entities[available[0]]
                else:
                    primary_ent = Entity(
                        id=Identifier(namespace="ENTITY", value=canon_id),
                        kind=EntityKind.CONCEPT,
                        label=extract_local_name(canon_id),
                    )
            clean_label = primary_ent.label if primary_ent.label else extract_local_name(canon_id)

            # Determine color & group from domain config
            kind_str = str(primary_ent.kind.value)
            group_name = kind_str.capitalize()
            color = self.domain_config.default_node_color

            for et in self.domain_config.entity_types:
                if et.name.lower() in kind_str.lower() or any(
                    p.lower() in canon_id.lower() for p in et.namespace_prefixes
                ):
                    group_name = et.group or et.name
                    color = et.color
                    break

            result.canonical_entities[canon_id] = {
                "id": canon_id,
                "canonical_id": primary_ent.id.canonical,
                "label": clean_label,
                "group": group_name,
                "color": color,
                "aliases": sorted(list(set(members))),
                "provenance_sources": [
                    all_entities[m].id.canonical for m in members if m in all_entities
                ],
                "properties": {},
                "literal_properties": {},
            }

        result.canonical_entities_count = len(result.canonical_entities)

        # Resolve graph names from caller parameters or fallback to graph attributes
        g_a_name = (
            graph_a_id.value
            if isinstance(graph_a_id, Identifier)
            else (str(graph_a_id) if graph_a_id else getattr(graph_a, "graph_id", "graph_a"))
        )
        g_b_name = (
            graph_b_id.value
            if isinstance(graph_b_id, Identifier)
            else (str(graph_b_id) if graph_b_id else getattr(graph_b, "graph_id", "graph_b"))
        )

        # --------------------------------------------------------------------
        # Extract and canonicalize literal properties from aligned assertions
        # --------------------------------------------------------------------
        def _process_aligned_literal_assertions(
            assertions: list[Assertion], source_graph_name: str
        ) -> None:
            for a in assertions:
                is_lit = False
                val_raw = ""
                if hasattr(a, "value") and not hasattr(a, "object"):
                    is_lit = True
                    val_raw = str(a.value.value)
                else:
                    pred_str = str(a.predicate)
                    obj_val = str(a.object.value)
                    if is_literal_value(pred_str, obj_val, self.domain_config.literal_rules):
                        is_lit = True
                        val_raw = obj_val

                if not is_lit:
                    continue

                norm_val = normalize_literal_format(val_raw, self.domain_config.literal_rules)
                p_local = extract_local_name(str(a.predicate))
                s_orig = str(a.subject.value)
                canon_id = alias_map.get(s_orig, s_orig)

                if canon_id in result.canonical_entities:
                    c_props = result.canonical_entities[canon_id]["properties"]
                    c_lit_props = result.canonical_entities[canon_id]["literal_properties"]
                    if p_local not in c_lit_props:
                        c_lit_props[p_local] = []

                    prov = a.provenance
                    if prov.graph_origin_id is None:
                        prov = prov.model_copy(update={"graph_origin_id": source_graph_name})

                    entry = {
                        "value": norm_val,
                        "source_graph": source_graph_name,
                        "provenance": prov,
                        "raw_value": val_raw,
                    }

                    if not any(
                        e["value"] == norm_val and e["source_graph"] == source_graph_name
                        for e in c_lit_props[p_local]
                    ):
                        c_lit_props[p_local].append(entry)

                    raw_values = [e["value"] for e in c_lit_props[p_local]]
                    c_props[p_local] = raw_values[0] if len(raw_values) == 1 else list(raw_values)

        _process_aligned_literal_assertions(aligned_assertions_a, g_a_name)
        _process_aligned_literal_assertions(aligned_assertions_b, g_b_name)

        # Fallback for any unaligned literal properties present on NormalizedGraph
        fallback_lit_props: dict[tuple[str, str, str], list[Any]] = {}
        for prop_key, values in graph_a.literal_properties.items():
            fallback_lit_props.setdefault((prop_key[0], prop_key[1], g_a_name), []).extend(values)
        for prop_key, values in graph_b.literal_properties.items():
            fallback_lit_props.setdefault((prop_key[0], prop_key[1], g_b_name), []).extend(values)

        for (s_orig, p_local, source_graph_name), vals in fallback_lit_props.items():
            canon_id = alias_map.get(s_orig, s_orig)
            if canon_id in result.canonical_entities:
                c_props = result.canonical_entities[canon_id]["properties"]
                c_lit_props = result.canonical_entities[canon_id]["literal_properties"]
                if p_local not in c_lit_props:
                    c_lit_props[p_local] = []
                for v in vals:
                    if not any(
                        e["value"] == v and e["source_graph"] == source_graph_name
                        for e in c_lit_props[p_local]
                    ):
                        c_lit_props[p_local].append(
                            {
                                "value": v,
                                "source_graph": source_graph_name,
                                "provenance": None,
                                "raw_value": str(v),
                            }
                        )
                raw_values = [e["value"] for e in c_lit_props[p_local]]
                c_props[p_local] = raw_values[0] if len(raw_values) == 1 else list(raw_values)

        # --------------------------------------------------------------------
        # Edge Redirection with Deterministic IDs and Metadata Retention
        # --------------------------------------------------------------------
        def redirect_assertion(a: Assertion, source_graph_name: str) -> Assertion:
            s_raw = a.subject.value
            o_raw = a.object.value
            s_canon = alias_map.get(s_raw, s_raw)
            o_canon = alias_map.get(o_raw, o_raw)

            if s_canon == s_raw and o_canon == o_raw:
                return a

            # Resolve canonical namespace if target entities exist in graph
            s_ns = (
                all_entities[s_canon].id.namespace
                if s_canon in all_entities
                else a.subject.namespace
            )
            o_ns = (
                all_entities[o_canon].id.namespace
                if o_canon in all_entities
                else a.object.namespace
            )

            # Deterministic hash-derived ID: ASSERT:canon_<sha256[:16]>
            hash_input = f"{a.id.canonical}:{s_canon}:{a.predicate}:{o_canon}".encode()
            canon_hash = hashlib.sha256(hash_input).hexdigest()[:16]
            redirected_id = Identifier(namespace="ASSERT", value=f"canon_{canon_hash}")

            # Structured derived provenance tracking
            redirected_prov = Provenance(
                assertion_origin=AssertionOrigin.DERIVED,
                agent_id=a.provenance.agent_id,
                activity_id=a.provenance.activity_id,
                asserted_at=a.provenance.asserted_at,
                method=a.provenance.method,
                input_assertion_refs=(a.id,),
                input_resource_refs=a.provenance.input_resource_refs,
                derivation_method="canonical_edge_redirection",
                source_artifact_id=a.provenance.source_artifact_id,
                graph_origin_id=a.provenance.graph_origin_id or source_graph_name,
            )

            # Preserve all metadata: confidence, evidence, context, status_at_creation
            return Assertion(
                id=redirected_id,
                subject=Identifier(namespace=s_ns, value=s_canon),
                predicate=a.predicate,
                object=Identifier(namespace=o_ns, value=o_canon),
                context=a.context,
                confidence=a.confidence,
                evidence=a.evidence,
                provenance=redirected_prov,
                status_at_creation=a.status_at_creation,
            )

        # --------------------------------------------------------------------
        # Deduplicate Identical Canonical Triples and Aggregate Provenance
        # --------------------------------------------------------------------
        redirected_assertions: list[Assertion] = [
            redirect_assertion(a, g_a_name) for a in aligned_assertions_a
        ] + [redirect_assertion(a, g_b_name) for a in aligned_assertions_b]

        canonicalized: list[Assertion] = []
        seen_triples: dict[tuple[str, str, str], Assertion] = {}
        triple_to_idx: dict[tuple[str, str, str], int] = {}
        dedup_count = 0

        for a in redirected_assertions:
            s_key = str(a.subject.value)
            p_key = extract_local_name(str(a.predicate)).lower()
            o_key = str(a.object.value)
            triple_key = (s_key, p_key, o_key)

            if triple_key not in seen_triples:
                seen_triples[triple_key] = a
                triple_to_idx[triple_key] = len(canonicalized)
                canonicalized.append(a)
            else:
                dedup_count += 1
                existing_a = seen_triples[triple_key]

                # Aggregate input assertion references across both sources
                def _get_input_refs(assertion: Assertion) -> list[Identifier]:
                    if (
                        assertion.provenance.assertion_origin == AssertionOrigin.DERIVED
                        and assertion.provenance.input_assertion_refs
                    ):
                        return list(assertion.provenance.input_assertion_refs)
                    return [assertion.id]

                merged_refs = tuple(dict.fromkeys(_get_input_refs(existing_a) + _get_input_refs(a)))

                # Merge input resource references
                merged_resource_refs = tuple(
                    dict.fromkeys(
                        existing_a.provenance.input_resource_refs + a.provenance.input_resource_refs
                    )
                )

                # Merge evidence (deduplicate by canonical evidence ID)
                seen_ev_ids: set[str] = set()
                merged_ev_list: list[Evidence] = []
                for ev in existing_a.evidence + a.evidence:
                    if ev.id.canonical not in seen_ev_ids:
                        seen_ev_ids.add(ev.id.canonical)
                        merged_ev_list.append(ev)
                merged_evidence = tuple(merged_ev_list)

                # Calibrate confidence: retain higher score
                merged_confidence = existing_a.confidence
                if a.confidence is not None:
                    if merged_confidence is None or a.confidence.score > merged_confidence.score:
                        merged_confidence = a.confidence

                # Deterministic merged assertion ID
                sorted_refs_str = ",".join(sorted(r.canonical for r in merged_refs))
                merged_hash_input = f"{existing_a.subject.canonical}:{existing_a.predicate}:{existing_a.object.canonical}:{sorted_refs_str}".encode()
                merged_hash = hashlib.sha256(merged_hash_input).hexdigest()[:16]
                merged_id = Identifier(namespace="ASSERT", value=f"canon_{merged_hash}")

                # Combine origin graphs
                orig_graphs = [
                    g
                    for g in [existing_a.provenance.graph_origin_id, a.provenance.graph_origin_id]
                    if g
                ]
                merged_graph_origin = "+".join(dict.fromkeys(orig_graphs)) if orig_graphs else None

                merged_prov = Provenance(
                    assertion_origin=AssertionOrigin.DERIVED,
                    agent_id=existing_a.provenance.agent_id,
                    activity_id=existing_a.provenance.activity_id,
                    asserted_at=existing_a.provenance.asserted_at,
                    method=existing_a.provenance.method or a.provenance.method,
                    input_assertion_refs=merged_refs,
                    input_resource_refs=merged_resource_refs,
                    derivation_method="canonical_deduplication",
                    source_artifact_id=existing_a.provenance.source_artifact_id
                    or a.provenance.source_artifact_id,
                    graph_origin_id=merged_graph_origin,
                )

                merged_assertion = Assertion(
                    id=merged_id,
                    subject=existing_a.subject,
                    predicate=existing_a.predicate,
                    object=existing_a.object,
                    context=existing_a.context or a.context,
                    confidence=merged_confidence,
                    evidence=merged_evidence,
                    provenance=merged_prov,
                    status_at_creation=existing_a.status_at_creation,
                )

                seen_triples[triple_key] = merged_assertion
                idx = triple_to_idx[triple_key]
                canonicalized[idx] = merged_assertion

        result.canonicalized_assertions = canonicalized
        result.deduplicated_facts_count = dedup_count
        result.complementary_facts_count = len(canonicalized)
        return result
