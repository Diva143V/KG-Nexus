"""Stage 2: Candidate Matcher for Knowledge Graph Fusion.

Multi-strategy candidate generation:
1. Exact IDs / External IDs / Identity Keys
2. Name and label similarity (exact, normalized, token overlap, string distance)
3. Neighbourhood / structural graph similarity (1-hop Jaccard overlap)
4. Optional embeddings (disabled by default to guarantee deterministic, zero-cost operation)
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from contracts.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
    resolve_embedding_provider,
)
from core.entities.entity import Entity
from core.fusion.normalizer import NormalizedGraph, normalize_label_text
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch
from sdk.domain_config import DomainFusionConfig


@dataclass
class EnhancedCandidateMatch:
    """Candidate match enriched with multi-signal score breakdown and evidence."""

    source_entity: Entity
    candidate_entity: Entity
    composite_score: float
    primary_method: str
    score_breakdown: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    activity_id: Identifier = field(
        default_factory=lambda: Identifier(namespace="ACT", value="act_candidate_gen")
    )

    def to_core_candidate_match(self) -> CandidateMatch:
        """Convert to core resolution CandidateMatch model."""
        return CandidateMatch(
            source_entity=self.source_entity,
            candidate_entity=self.candidate_entity,
            ranking_score=round(self.composite_score, 4),
            ranking_method=self.primary_method,
            activity_id=self.activity_id,
        )


def calculate_string_similarity(s1: str, s2: str) -> float:
    """Compute string similarity using SequenceMatcher (Levenshtein/Ratcliff-Obershelp)."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    return difflib.SequenceMatcher(None, s1, s2).ratio()


def calculate_token_jaccard(s1: str, s2: str) -> float:
    """Compute token-level Jaccard similarity."""
    tokens1 = set(re.findall(r"\w+", s1.lower()))
    tokens2 = set(re.findall(r"\w+", s2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def build_entity_surface_text(
    ent: Entity,
    graph: NormalizedGraph,
    entity_key: str | None = None,
    domain_config: DomainFusionConfig | None = None,
) -> str:
    """Construct structured contextual text surface for semantic embedding.

    Includes entity label, kind/type, aliases/synonyms, and literal descriptions.
    """
    label = ent.label or str(ent.id.value)
    kind = str(ent.kind) if ent.kind else "Entity"

    parts = [f"{label} [{kind}]"]

    possible_keys = [k for k in (entity_key, str(ent.id), ent.id.canonical, str(ent.id.value)) if k]

    # Collect synonyms and aliases
    aliases: list[str] = []
    # Use entity-type-specific alias property names from config, falling back to generic set
    generic_alias_keys = {
        "synonym",
        "alias",
        "altlabel",
        "alternate_name",
    }
    entity_specific_alias_keys: set[str] = set()
    if domain_config is not None:
        for et in domain_config.entity_types:
            for alias_name in getattr(et, "alias_property_names", ()):
                entity_specific_alias_keys.add(alias_name.lower())
    alias_keys = generic_alias_keys | entity_specific_alias_keys
    for k in possible_keys:
        for a_key in alias_keys:
            prop_key = (k, a_key)
            if prop_key in graph.literal_properties:
                for val in graph.literal_properties[prop_key]:
                    val_str = str(val).strip()
                    if val_str and val_str not in aliases:
                        aliases.append(val_str)
    if aliases:
        parts.append(f"Aliases: {', '.join(aliases[:5])}")

    # Collect descriptions or definitions
    desc_keys = {"description", "definition", "comment", "summary", "notes"}
    for k in possible_keys:
        for d_key in desc_keys:
            prop_key = (k, d_key)
            if prop_key in graph.literal_properties:
                for val in graph.literal_properties[prop_key]:
                    val_str = str(val).strip()
                    if val_str:
                        parts.append(f"Description: {val_str}")
                        break
                if len(parts) > 2:
                    break
        if len(parts) > 2:
            break

    return ". ".join(parts)


class CandidateFinder:
    """Executes Stage 2: Candidate Matching."""

    def __init__(
        self,
        domain_config: DomainFusionConfig,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.domain_config = domain_config
        self._embedding_provider = embedding_provider

    def build_neighborhood_map(self, graph: NormalizedGraph) -> dict[str, set[str]]:
        """Build 1-hop neighbor adjacency sets for each entity."""
        adj: dict[str, set[str]] = {eid: set() for eid in graph.entities}
        for a in graph.relational_assertions:
            s_val = str(a.subject.value)
            o_val = str(a.object.value)
            if s_val in adj:
                adj[s_val].add(o_val)
            if o_val in adj:
                adj[o_val].add(s_val)
        return adj

    def find_candidates(
        self,
        graph_a: NormalizedGraph,
        graph_b: NormalizedGraph,
        activity_id: Identifier,
    ) -> list[EnhancedCandidateMatch]:
        """Find candidate pairs across graph A and graph B."""
        candidates: list[EnhancedCandidateMatch] = []
        seen_pairs: set[tuple[str, str]] = set()

        strategy = self.domain_config.match_strategy
        role_suffixes = strategy.role_suffixes_to_strip

        adj_a = self.build_neighborhood_map(graph_a)
        adj_b = self.build_neighborhood_map(graph_b)

        # Precompute normalized labels and identity key lookups
        norm_labels_a = {
            eid: normalize_label_text(ent.label or eid, role_suffixes)
            for eid, ent in graph_a.entities.items()
        }
        norm_labels_b = {
            eid: normalize_label_text(ent.label or eid, role_suffixes)
            for eid, ent in graph_b.entities.items()
        }

        # Build identity key lookup for graph B
        id_key_map_b: dict[tuple[str, str], list[str]] = {}
        for et in self.domain_config.entity_types:
            for key in et.identity_keys:
                for eid in graph_b.entities:
                    prop_key = (eid, key)
                    if prop_key in graph_b.literal_properties:
                        for val in graph_b.literal_properties[prop_key]:
                            lookup_key = (key, str(val).strip().lower())
                            if lookup_key not in id_key_map_b:
                                id_key_map_b[lookup_key] = []
                            if eid not in id_key_map_b[lookup_key]:
                                id_key_map_b[lookup_key].append(eid)

        # Strategy 4: Batch Pre-computation for Embeddings
        vectors_a: dict[str, tuple[float, ...]] = {}
        vectors_b: dict[str, tuple[float, ...]] = {}
        active_provider = None

        if strategy.enable_embeddings:
            if self._embedding_provider is not None:
                active_provider = self._embedding_provider
            else:
                active_provider = resolve_embedding_provider(strategy)

            if not active_provider.is_available():
                raise EmbeddingProviderUnavailableError(
                    f"Embedding provider '{active_provider.provider_type}' for model '{active_provider.model_id}' "
                    "is unavailable. Check daemon or package installation."
                )

            surfaces_a = [
                build_entity_surface_text(ent, graph_a, eid, self.domain_config)
                for eid, ent in graph_a.entities.items()
            ]
            surfaces_b = [
                build_entity_surface_text(ent, graph_b, eid, self.domain_config)
                for eid, ent in graph_b.entities.items()
            ]
            batch_sz = getattr(strategy, "embedding_batch_size", 32)

            def _batch_encode(texts: list[str]) -> list[tuple[float, ...]]:
                res: list[tuple[float, ...]] = []
                for i in range(0, len(texts), batch_sz):
                    res.extend(active_provider.embed(texts[i : i + batch_sz]))
                return res

            embeddings_a = _batch_encode(surfaces_a)
            embeddings_b = _batch_encode(surfaces_b)

            vectors_a = dict(zip(graph_a.entities.keys(), embeddings_a, strict=False))
            vectors_b = dict(zip(graph_b.entities.keys(), embeddings_b, strict=False))

        for s_id, s_ent in graph_a.entities.items():
            s_label_norm = norm_labels_a[s_id]
            s_neighbors = adj_a.get(s_id, set())

            for t_id, t_ent in graph_b.entities.items():
                pair_key = (s_id, t_id)
                if pair_key in seen_pairs:
                    continue

                t_label_norm = norm_labels_b[t_id]
                t_neighbors = adj_b.get(t_id, set())

                scores: dict[str, float] = {}
                evidence: list[str] = []

                # Strategy 1: Exact IDs / External Identity Keys
                if strategy.enable_exact_id:
                    if s_id == t_id or s_ent.id.canonical == t_ent.id.canonical:
                        scores["exact_id"] = 1.0
                        evidence.append(f"Identical IRI/Identifier: {s_id}")
                    else:
                        # Check identity keys - lookup in pre-built map to handle collisions
                        identity_key_match = False
                        for et in self.domain_config.entity_types:
                            for key in et.identity_keys:
                                prop_key_a = (s_id, key)
                                if prop_key_a in graph_a.literal_properties:
                                    for val in graph_a.literal_properties[prop_key_a]:
                                        k_val = str(val).strip().lower()
                                        # Lookup - check if t_id is in the list of entities with this identity key value
                                        lookup_key = (key, k_val)
                                        if (
                                            lookup_key in id_key_map_b
                                            and t_id in id_key_map_b[lookup_key]
                                        ):
                                            scores["exact_id"] = 1.0
                                            evidence.append(
                                                f"Matching Identity Key '{key}': {k_val}"
                                            )
                                            identity_key_match = True
                                            break
                                    if identity_key_match:
                                        break
                                if identity_key_match:
                                    break
                # Strategy 2: Name and Label Similarity
                if strategy.enable_label_similarity:
                    if s_label_norm and t_label_norm:
                        if s_label_norm == t_label_norm:
                            scores["label_similarity"] = 0.95
                            evidence.append(f"Normalized label exact match: '{s_label_norm}'")
                        else:
                            sim = calculate_string_similarity(s_label_norm, t_label_norm)
                            jaccard = calculate_token_jaccard(s_label_norm, t_label_norm)
                            combined_label_sim = max(sim, jaccard)

                            sim_threshold = getattr(strategy, "label_similarity_threshold", 0.70)
                            if combined_label_sim >= sim_threshold:
                                scores["label_similarity"] = combined_label_sim
                                evidence.append(
                                    f"String/token similarity: {combined_label_sim:.2f} ('{s_label_norm}' vs '{t_label_norm}')"
                                )
                            elif s_label_norm in t_label_norm or t_label_norm in s_label_norm:
                                substring_score = getattr(
                                    strategy, "label_substring_match_score", 0.75
                                )
                                scores["label_similarity"] = substring_score
                                evidence.append(
                                    f"Label substring match ('{s_label_norm}' in '{t_label_norm}')"
                                )

                # Strategy 3: Structural / Neighborhood Similarity
                if strategy.enable_structural_similarity and s_neighbors and t_neighbors:
                    # Compare 1-hop neighbor overlap
                    norm_s_nbrs = {
                        norm_labels_a.get(n, normalize_label_text(n, role_suffixes))
                        for n in s_neighbors
                    }
                    norm_t_nbrs = {
                        norm_labels_b.get(n, normalize_label_text(n, role_suffixes))
                        for n in t_neighbors
                    }
                    intersect = norm_s_nbrs.intersection(norm_t_nbrs)
                    union = norm_s_nbrs.union(norm_t_nbrs)
                    if union:
                        nbr_jaccard = len(intersect) / len(union)
                        if nbr_jaccard > 0.0:
                            scores["structural_similarity"] = nbr_jaccard
                            evidence.append(
                                f"Neighborhood overlap Jaccard {nbr_jaccard:.2f} ({len(intersect)} shared neighbors)"
                            )

                # Strategy 4: Real Neural Vector Embedding Similarity
                if strategy.enable_embeddings and active_provider:
                    vec_a = vectors_a.get(s_id)
                    vec_b = vectors_b.get(t_id)
                    if vec_a is not None and vec_b is not None:
                        cos_sim = max(
                            0.0, min(1.0, sum(u * v for u, v in zip(vec_a, vec_b, strict=False)))
                        )
                        embed_threshold = getattr(strategy, "embedding_threshold", 0.75)
                        if cos_sim >= embed_threshold or (scores and cos_sim >= 0.40):
                            scores["embedding_similarity"] = round(cos_sim, 4)
                            evidence.append(
                                f"Embedding vector similarity: {cos_sim:.4f} "
                                f"(model: {active_provider.model_id}, provider: {active_provider.provider_type})"
                            )

                if not scores:
                    continue

                # Calculate composite score from configured strategy weights
                exact_w = strategy.exact_id_weight
                label_w = strategy.label_similarity_weight
                struct_w = strategy.structural_similarity_weight
                embed_w = strategy.embedding_weight

                exact_score = scores.get("exact_id", 0.0)
                label_score = scores.get("label_similarity", 0.0)
                struct_score = scores.get("structural_similarity", 0.0)
                embed_score = scores.get("embedding_similarity", 0.0)

                # Composite score calculation per Requirement 6:
                # exact_id_weight * exact_score + label_similarity_weight * label_score + structural_similarity_weight * struct_score + embedding_weight * embed_score
                raw_composite = (
                    exact_w * exact_score
                    + label_w * label_score
                    + struct_w * struct_score
                    + embed_w * embed_score
                )
                composite = min(1.0, raw_composite)

                if "exact_id" in scores and exact_score >= 1.0:
                    primary_method = "exact_id"
                elif label_score >= getattr(strategy, "normalized_label_threshold", 0.90):
                    primary_method = "normalized_label"
                elif struct_score >= getattr(strategy, "structural_neighborhood_threshold", 0.60):
                    primary_method = "structural_neighborhood"
                elif embed_score >= getattr(strategy, "embedding_threshold", 0.75):
                    primary_method = "semantic_embedding"
                else:
                    primary_method = "label_similarity"

                if composite > 0.0:
                    seen_pairs.add(pair_key)
                    candidates.append(
                        EnhancedCandidateMatch(
                            source_entity=s_ent,
                            candidate_entity=t_ent,
                            composite_score=round(composite, 4),
                            primary_method=primary_method,
                            score_breakdown=scores,
                            evidence=evidence,
                            activity_id=activity_id,
                        )
                    )

        # Sort candidates descending by composite score
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        return candidates
