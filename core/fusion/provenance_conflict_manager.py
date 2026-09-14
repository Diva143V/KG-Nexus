"""Stage 6: Provenance and Conflict Management Module for Knowledge Graph Fusion.

Responsibilities:
- Record exact assertion lineage (source graph, original assertion ID, timestamp, confidence, agent).
- Detect contradictory predicate conflicts and single-valued functional collisions.
- Apply 4-tier deterministic resolution:
  1. Evidence / Confidence Score
  2. Predicate-specific source authority precedence
  3. Default graph precedence
  4. Deterministic canonical hash tie-breaker
- Maintain conflicting values with explicit status and resolution reason.
- Support all ConflictModes (CONFLICT_PRESERVE, CONFLICT_REJECT, CONFLICT_REVIEW, CONFLICT_POLICY_DECISION).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.models import ConflictMode
from core.fusion.normalizer import extract_local_name
from core.identifiers.identifier import Identifier
from sdk.domain_config import DomainFusionConfig


def _is_assertion_from_graph(
    a: Assertion,
    target_graph_id: Identifier | str | None,
    fallback_names: tuple[str, ...] = (),
) -> bool:
    """Determine whether an assertion originates from a specific graph."""
    import re

    target_names: list[str] = [fn.lower() for fn in fallback_names if fn]
    if target_graph_id is not None:
        target_val = (
            target_graph_id.value
            if isinstance(target_graph_id, Identifier)
            else str(target_graph_id)
        )
        t_low = target_val.lower()
        if t_low not in target_names:
            target_names.append(t_low)

    # 1. Check structured provenance fields first (most reliable)
    if a.provenance:
        g_orig = getattr(a.provenance, "graph_origin_id", None)
        if g_orig:
            g_orig_low = str(g_orig).lower()
            if g_orig_low in target_names:
                return True

        src_art = getattr(a.provenance, "source_artifact_id", None)
        if src_art:
            src_art_low = str(src_art).lower()
            for name in target_names:
                if len(name) > 1 and (
                    src_art_low == name
                    or src_art_low.startswith(f"{name}:")
                    or src_art_low.startswith(f"{name}_")
                ):
                    return True

    # 2. Check assertion ID and provenance tokens with structured boundaries (avoid single-char substring traps)
    def _matches_tokens(s: str) -> bool:
        s_low = s.lower()
        tokens = set(re.split(r"[:_\-/#.\s]+", s_low))
        for name in target_names:
            if not name:
                continue
            if s_low == name or s_low.startswith(f"{name}:") or s_low.startswith(f"{name}_"):
                return True
            if len(name) > 1 and name in tokens:
                return True
            if len(name) == 1 and name in tokens and ("graph" in s_low or "source" in s_low):
                return True
        return False

    if _matches_tokens(str(a.id.value)) or _matches_tokens(str(a.id.canonical)):
        return True

    if a.provenance:
        for ref in getattr(a.provenance, "input_resource_refs", ()):
            if _matches_tokens(f"{ref.value} {ref.canonical}"):
                return True
        if a.provenance.agent_id and _matches_tokens(str(a.provenance.agent_id.value)):
            return True
        if a.provenance.activity_id and _matches_tokens(str(a.provenance.activity_id.value)):
            return True

    return False


def resolve_conflict_winner_deterministic(
    a1: Assertion,
    a2: Assertion,
    domain_config: DomainFusionConfig,
    ground_truth_source_ids: set[str] | None = None,
    *,
    graph_a_id: Identifier | str | None = None,
    graph_b_id: Identifier | str | None = None,
) -> tuple[Assertion, Assertion, str]:
    """Deterministically determine winning and losing assertions across 5 tiers (including ground truth)."""
    gt_sources = set(s.lower() for s in (ground_truth_source_ids or set()))
    declared_gt = set(s.lower() for s in domain_config.source_identity.ground_truth_sources)
    gt_set = gt_sources | declared_gt

    # Tier 0: Ultimate Ground Truth Authority Precedence
    def _is_ground_truth(a: Assertion) -> bool:
        if not gt_set:
            return False
        for ref in a.provenance.input_resource_refs:
            if ref.value.lower() in gt_set or ref.canonical.lower() in gt_set:
                return True
        return False

    gt1 = _is_ground_truth(a1)
    gt2 = _is_ground_truth(a2)
    if gt1 and not gt2:
        return a1, a2, "ULTIMATE_GROUND_TRUTH_AUTHORITY"
    if gt2 and not gt1:
        return a2, a1, "ULTIMATE_GROUND_TRUTH_AUTHORITY"

    # Tier 1: Evidence / Confidence Score
    c1 = getattr(a1.provenance, "confidence", 1.0)
    c2 = getattr(a2.provenance, "confidence", 1.0)
    if c1 > c2:
        return a1, a2, "HIGHER_EVIDENCE_CONFIDENCE_SCORE"
    if c2 > c1:
        return a2, a1, "HIGHER_EVIDENCE_CONFIDENCE_SCORE"

    # Tier 2: Predicate-Specific Source Authority Precedence
    p_local1 = extract_local_name(str(a1.predicate))
    p_local2 = extract_local_name(str(a2.predicate))
    authorities = domain_config.conflict_rules.predicate_authorities
    if authorities:
        auth1 = authorities.get(p_local1)
        auth2 = authorities.get(p_local2)
        if auth1 and not auth2:
            return a1, a2, f"PREDICATE_SOURCE_AUTHORITY ({p_local1})"
        if auth2 and not auth1:
            return a2, a1, f"PREDICATE_SOURCE_AUTHORITY ({p_local2})"

    # Tier 3: Explicit Graph Precedence
    default_prec = domain_config.conflict_rules.default_graph_precedence.lower()
    a1_is_a = _is_assertion_from_graph(a1, graph_a_id, fallback_names=("rel_graph_a", "graph_a"))
    a2_is_a = _is_assertion_from_graph(a2, graph_a_id, fallback_names=("rel_graph_a", "graph_a"))
    a1_is_b = _is_assertion_from_graph(a1, graph_b_id, fallback_names=("rel_graph_b", "graph_b"))
    a2_is_b = _is_assertion_from_graph(a2, graph_b_id, fallback_names=("rel_graph_b", "graph_b"))

    if default_prec == "graph_a":
        if a1_is_a and not a2_is_a:
            return a1, a2, "GRAPH_A_DEFAULT_PRECEDENCE"
        if a2_is_a and not a1_is_a:
            return a2, a1, "GRAPH_A_DEFAULT_PRECEDENCE"
    elif default_prec == "graph_b":
        if a1_is_b and not a2_is_b:
            return a1, a2, "GRAPH_B_DEFAULT_PRECEDENCE"
        if a2_is_b and not a1_is_b:
            return a2, a1, "GRAPH_B_DEFAULT_PRECEDENCE"

    # Tier 4: Deterministic Canonical Hash Tie-Breaker
    if str(a1.id.canonical) <= str(a2.id.canonical):
        return a1, a2, "DETERMINISTIC_CANONICAL_HASH_TIE_BREAKER"
    else:
        return a2, a1, "DETERMINISTIC_CANONICAL_HASH_TIE_BREAKER"


@dataclass
class ProvenanceConflictResult:
    """Result of Stage 6 Provenance and Conflict Management."""

    reconciled_assertions: list[Assertion] = field(default_factory=list)
    dedup_count: int = 0
    conflict_count: int = 0
    conflict_report: dict[str, Any] = field(default_factory=dict)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    functional_collisions: list[dict[str, Any]] = field(default_factory=list)
    deduplications: list[dict[str, Any]] = field(default_factory=list)
    review_required: list[dict[str, Any]] = field(default_factory=list)


class ProvenanceConflictManager:
    """Executes Stage 6: Provenance Tracking & Conflict Resolution."""

    def __init__(self, domain_config: DomainFusionConfig) -> None:
        self.domain_config = domain_config

    def reconcile(
        self,
        canonicalized_assertions: list[Assertion],
        conflict_mode: ConflictMode = ConflictMode.CONFLICT_PRESERVE,
        ground_truth_source_ids: set[str] | None = None,
        *,
        graph_a_id: Identifier | str | None = None,
        graph_b_id: Identifier | str | None = None,
    ) -> ProvenanceConflictResult:
        """Reconcile canonical assertions, detect contradictions, apply conflict resolution."""
        result = ProvenanceConflictResult()
        reconciled: list[Assertion] = []
        seen_triples: dict[tuple[str, str, str], Assertion] = {}
        so_to_assertions: dict[tuple[str, str], list[Assertion]] = {}
        sp_to_assertions: dict[tuple[str, str], list[Assertion]] = {}

        opposing_set = {
            (p[0].lower(), p[1].lower())
            for p in self.domain_config.conflict_rules.opposing_predicates
        }
        opposing_set.update(
            {
                (p[1].lower(), p[0].lower())
                for p in self.domain_config.conflict_rules.opposing_predicates
            }
        )
        functional_set = {
            f.lower() for f in self.domain_config.conflict_rules.functional_predicates
        }

        for a in canonicalized_assertions:
            s_val = str(a.subject.value)
            p_val = str(a.predicate)
            p_local = extract_local_name(p_val).lower()
            o_val = str(a.object.value)
            triple_key = (s_val, p_local, o_val)

            # 1. Exact Triple Deduplication
            if triple_key in seen_triples:
                result.dedup_count += 1
                prev_a = seen_triples[triple_key]
                should_purge = conflict_mode in (
                    ConflictMode.CONFLICT_REJECT,
                    ConflictMode.CONFLICT_POLICY_DECISION,
                )
                result.deduplications.append(
                    {
                        "kept_assertion_id": str(prev_a.id.canonical),
                        "duplicate_assertion_id": str(a.id.canonical),
                        "subject_id": s_val,
                        "predicate_iri": p_val,
                        "object_id": o_val,
                        "action": "EXACT_TRIPLE_PURGED"
                        if should_purge
                        else "EXACT_TRIPLE_PRESERVED",
                    }
                )
                if should_purge:
                    continue
                else:
                    reconciled.append(a)
                continue

            # 2. Contradictory Predicate Conflict Detection & Deterministic Resolution
            so_key = (s_val, o_val)
            is_conflicting = False
            prev_conflicting_assertion: Assertion | None = None

            if so_key in so_to_assertions:
                for prev_a in so_to_assertions[so_key]:
                    prev_p_local = extract_local_name(str(prev_a.predicate)).lower()
                    if (prev_p_local, p_local) in opposing_set:
                        is_conflicting = True
                        result.conflict_count += 1
                        prev_conflicting_assertion = prev_a
                        break

            if is_conflicting and prev_conflicting_assertion is not None:
                winner, loser, res_method = resolve_conflict_winner_deterministic(
                    prev_conflicting_assertion,
                    a,
                    self.domain_config,
                    ground_truth_source_ids=ground_truth_source_ids,
                    graph_a_id=graph_a_id,
                    graph_b_id=graph_b_id,
                )

                if conflict_mode == ConflictMode.CONFLICT_REVIEW:
                    action_str = "FLAGGED_FOR_HUMAN_REVIEW"
                elif conflict_mode in (
                    ConflictMode.CONFLICT_REJECT,
                    ConflictMode.CONFLICT_POLICY_DECISION,
                ):
                    action_str = "REJECTED_LOSING_CLAIM"
                else:
                    action_str = "PRESERVED_BOTH_CLAIMS"

                conflict_entry = {
                    "winning_assertion_id": str(winner.id.canonical),
                    "losing_assertion_id": str(loser.id.canonical),
                    "subject_id": s_val,
                    "object_id": o_val,
                    "winning_predicate_iri": str(winner.predicate),
                    "losing_predicate_iri": str(loser.predicate),
                    "normalized_conflict": f"{extract_local_name(str(winner.predicate))} ↔ {extract_local_name(str(loser.predicate))}",
                    "conflict_category": "CONTRADICTORY_PREDICATE_CONFLICT",
                    "resolution_method": res_method,
                    "action": action_str,
                }
                result.contradictions.append(conflict_entry)

                if conflict_mode == ConflictMode.CONFLICT_REVIEW:
                    result.review_required.append(conflict_entry)

                if conflict_mode in (
                    ConflictMode.CONFLICT_REJECT,
                    ConflictMode.CONFLICT_POLICY_DECISION,
                ):
                    if loser is prev_conflicting_assertion:
                        if prev_conflicting_assertion in reconciled:
                            reconciled.remove(prev_conflicting_assertion)
                        if winner not in reconciled:
                            reconciled.append(winner)
                            seen_triples[triple_key] = winner
                    continue

            # 3. Single-Valued Functional Predicate Collision Detection & Resolution
            sp_key = (s_val, p_local)
            is_functional_collision = False
            prev_functional_assertion: Assertion | None = None

            if not is_conflicting and p_local in functional_set and sp_key in sp_to_assertions:
                for prev_a in sp_to_assertions[sp_key]:
                    prev_o_val = str(prev_a.object.value)
                    if prev_o_val != o_val:
                        is_functional_collision = True
                        result.conflict_count += 1
                        prev_functional_assertion = prev_a
                        break

            if is_functional_collision and prev_functional_assertion is not None:
                winner, loser, res_method = resolve_conflict_winner_deterministic(
                    prev_functional_assertion,
                    a,
                    self.domain_config,
                    ground_truth_source_ids=ground_truth_source_ids,
                    graph_a_id=graph_a_id,
                    graph_b_id=graph_b_id,
                )

                if conflict_mode == ConflictMode.CONFLICT_REVIEW:
                    action_str = "FLAGGED_FOR_HUMAN_REVIEW"
                elif conflict_mode in (
                    ConflictMode.CONFLICT_REJECT,
                    ConflictMode.CONFLICT_POLICY_DECISION,
                ):
                    action_str = "REJECTED_LOSING_CLAIM"
                else:
                    action_str = "PRESERVED_BOTH_CLAIMS"

                func_conflict_entry = {
                    "winning_assertion_id": str(winner.id.canonical),
                    "losing_assertion_id": str(loser.id.canonical),
                    "subject_id": s_val,
                    "predicate_iri": p_val,
                    "winning_value": str(winner.object.value),
                    "losing_value": str(loser.object.value),
                    "normalized_conflict": f"{str(winner.object.value)} ≠ {str(loser.object.value)} for {extract_local_name(p_val)}",
                    "conflict_category": "FUNCTIONAL_PREDICATE_COLLISION",
                    "resolution_method": res_method,
                    "action": action_str,
                }
                result.functional_collisions.append(func_conflict_entry)

                if conflict_mode == ConflictMode.CONFLICT_REVIEW:
                    result.review_required.append(func_conflict_entry)

                if conflict_mode in (
                    ConflictMode.CONFLICT_REJECT,
                    ConflictMode.CONFLICT_POLICY_DECISION,
                ):
                    if loser is prev_functional_assertion:
                        if prev_functional_assertion in reconciled:
                            reconciled.remove(prev_functional_assertion)
                        if winner not in reconciled:
                            reconciled.append(winner)
                            seen_triples[triple_key] = winner
                    continue

            seen_triples[triple_key] = a
            if so_key not in so_to_assertions:
                so_to_assertions[so_key] = []
            so_to_assertions[so_key].append(a)

            if sp_key not in sp_to_assertions:
                sp_to_assertions[sp_key] = []
            sp_to_assertions[sp_key].append(a)

            reconciled.append(a)

        result.reconciled_assertions = reconciled
        result.conflict_report = {
            "summary": {
                "conflict_mode": conflict_mode.value,
                "total_contradictions_detected": len(result.contradictions),
                "total_functional_collisions_detected": len(result.functional_collisions),
                "total_conflicts_detected": result.conflict_count,
                "total_deduplicated_triples": result.dedup_count,
                "review_required_count": len(result.review_required),
                "reconciled_triple_count": len(reconciled),
            },
            "contradiction_conflicts": result.contradictions,
            "functional_collisions": result.functional_collisions,
            "review_required_conflicts": result.review_required,
            "deduplicated_triples": result.deduplications,
        }
        return result
