"""Stage 5: Canonical Entities and Facts Creator for Knowledge Graph Fusion.

Responsibilities:
- Build single canonical entity nodes for each matched entity cluster (via Disjoint Set Union).
- Preserve all original IDs as aliases and provenance sources on canonical entities.
- Redirect all source edges (subject and object) to canonical nodes.
- Deduplicate equivalent facts (identical canonical subject, predicate, object) while aggregating provenance.
- Preserve complementary facts (distinct attributes and relations from both graphs are retained).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.normalizer import NormalizedGraph, extract_local_name
from core.identifiers.identifier import Identifier
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

        {et.name.lower(): et for et in self.domain_config.entity_types}

        for canon_id, members in clusters.items():
            primary_ent = all_entities[canon_id]
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

        # Attach normalized literal properties to canonical entities
        all_lit_props: dict[
            tuple[str, str, str], list[Any]
        ] = {}  # (subject, predicate_local, source_graph) -> values
        for prop_key, values in graph_a.literal_properties.items():
            s_orig = prop_key[0]
            p_local = prop_key[1]
            all_lit_props.setdefault((s_orig, p_local, "graph_a"), []).extend(values)
        for prop_key, values in graph_b.literal_properties.items():
            s_orig = prop_key[0]
            p_local = prop_key[1]
            all_lit_props.setdefault((s_orig, p_local, "graph_b"), []).extend(values)

        for (s_orig, p_local, source_graph), vals in all_lit_props.items():
            canon_id = alias_map.get(s_orig, s_orig)
            if canon_id in result.canonical_entities:
                c_props = result.canonical_entities[canon_id]["properties"]
                c_lit_props = result.canonical_entities[canon_id]["literal_properties"]
                if p_local not in c_lit_props:
                    c_lit_props[p_local] = []
                # Track source graph provenance with each value
                for v in vals:
                    v_entry = (v, source_graph)
                    if v_entry not in c_lit_props[p_local]:
                        c_lit_props[p_local].append(v_entry)
                raw_values = [v for v, _ in c_lit_props[p_local]]
                c_props[p_local] = raw_values[0] if len(raw_values) == 1 else list(raw_values)

        # Redirect source edges to canonical nodes
        def redirect_assertion(a: Assertion) -> Assertion:
            s_raw = a.subject.value
            o_raw = a.object.value
            s_canon = alias_map.get(s_raw, s_raw)
            o_canon = alias_map.get(o_raw, o_raw)

            if s_canon == s_raw and o_canon == o_raw:
                return a

            return Assertion(
                id=a.id,
                subject=Identifier(namespace=a.subject.namespace, value=s_canon),
                predicate=a.predicate,
                object=Identifier(namespace=a.object.namespace, value=o_canon),
                provenance=a.provenance,
            )

        all_aligned_assertions = [redirect_assertion(a) for a in aligned_assertions_a] + [
            redirect_assertion(a) for a in aligned_assertions_b
        ]

        result.canonicalized_assertions = all_aligned_assertions
        return result
