"""Stage 4: Confidence Decider for Knowledge Graph Fusion.

Responsibilities:
- Evaluate candidate match confidence against conservative domain thresholds:
  - High confidence (score >= high_threshold) -> MERGE_AUTOMATIC
  - Medium confidence (review_threshold <= score < high_threshold) -> REVIEW_REQUIRED
  - Low confidence (score < review_threshold) -> KEEP_SEPARATE
- Enforce strict conservatism: uncertain matches are NEVER automatically merged.
- Produce detailed decision rationale and score breakdowns for full auditability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.models import AuditReportEntry, DecisionOutcome
from sdk.domain_config import DomainFusionConfig


@dataclass
class MatchDecision:
    """Decision record for a single candidate match."""

    candidate: EnhancedCandidateMatch
    outcome: DecisionOutcome
    score: float
    reason: str
    evidence: list[str]
    score_breakdown: dict[str, float]
    mappings_applied: list[str] = field(default_factory=list)


@dataclass
class ConfidenceDeciderResult:
    """Result of Stage 4 Confidence Evaluation."""

    auto_merged_pairs: list[tuple[str, str]] = field(default_factory=list)
    review_required_pairs: list[dict[str, Any]] = field(default_factory=list)
    kept_separate_pairs: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[MatchDecision] = field(default_factory=list)
    audit_entries: list[AuditReportEntry] = field(default_factory=list)


class ConfidenceDecider:
    """Executes Stage 4: Match Confidence Decisioning."""

    def __init__(self, domain_config: DomainFusionConfig) -> None:
        self.domain_config = domain_config

    def evaluate_candidates(
        self,
        aligned_candidates: list[EnhancedCandidateMatch],
    ) -> ConfidenceDeciderResult:
        """Evaluate candidate matches and route into Auto-Merge, Review, or Keep-Separate."""
        result = ConfidenceDeciderResult()
        thresholds = self.domain_config.confidence_thresholds

        for cand in aligned_candidates:
            s_val = str(cand.source_entity.id.value)
            t_val = str(cand.candidate_entity.id.value)
            score = cand.composite_score

            # Check decision bands
            if score >= thresholds.high_confidence_threshold:
                outcome = DecisionOutcome.MERGE_AUTOMATIC
                reason = f"Score {score:.2f} >= high confidence threshold ({thresholds.high_confidence_threshold:.2f})"
                action_str = "AUTO_MERGE_CANONICAL"
                result.auto_merged_pairs.append((s_val, t_val))
            elif score >= thresholds.review_threshold:
                outcome = DecisionOutcome.REVIEW_REQUIRED
                reason = f"Borderline score {score:.2f} in review band [{thresholds.review_threshold:.2f}, {thresholds.high_confidence_threshold:.2f})"
                action_str = "FLAGGED_FOR_HUMAN_REVIEW"
                result.review_required_pairs.append(
                    {
                        "source_id": s_val,
                        "target_id": t_val,
                        "score": round(score, 4),
                        "evidence": cand.evidence,
                        "breakdown": cand.score_breakdown,
                    }
                )
            else:
                outcome = DecisionOutcome.KEEP_SEPARATE
                reason = f"Low confidence score {score:.2f} < review threshold ({thresholds.review_threshold:.2f})"
                action_str = "KEPT_SEPARATE_ENTITIES"
                result.kept_separate_pairs.append(
                    {
                        "source_id": s_val,
                        "target_id": t_val,
                        "score": round(score, 4),
                        "reason": reason,
                    }
                )

            decision = MatchDecision(
                candidate=cand,
                outcome=outcome,
                score=score,
                reason=reason,
                evidence=list(cand.evidence),
                score_breakdown=dict(cand.score_breakdown),
                mappings_applied=[e for e in cand.evidence if "mapping" in e.lower()],
            )
            result.decisions.append(decision)

            audit_entry = AuditReportEntry(
                source_id=s_val,
                target_id=t_val,
                match_score=round(score, 4),
                score_breakdown=cand.score_breakdown,
                evidence=cand.evidence,
                decision=outcome,
                mappings_applied=decision.mappings_applied,
                original_assertion_ids=[
                    str(cand.source_entity.id.canonical),
                    str(cand.candidate_entity.id.canonical),
                ],
                conflict_resolution_reason=reason,
                action_taken=action_str,
            )
            result.audit_entries.append(audit_entry)

        return result
