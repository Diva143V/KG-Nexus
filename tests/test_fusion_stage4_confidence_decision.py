"""Unit Tests for Stage 4: Confidence Decision Engine.

Verifies:
- High confidence (score >= high_threshold) -> MERGE_AUTOMATIC
- Medium confidence (review_threshold <= score < high_threshold) -> REVIEW_REQUIRED
- Low confidence (score < review_threshold) -> KEEP_SEPARATE
- Strict conservatism: uncertain matches are never automatically merged.
- Audit trail generation with score breakdowns and evidence.
"""

from core.entities.entity import Entity, EntityKind
from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.confidence_decider import ConfidenceDecider
from core.fusion.models import DecisionOutcome
from core.identifiers.identifier import Identifier
from sdk.domain_config import ConfidenceThresholds, DomainFusionConfig


def _make_candidate(src_id: str, tgt_id: str, score: float) -> EnhancedCandidateMatch:
    return EnhancedCandidateMatch(
        source_entity=Entity(
            id=Identifier(namespace="EX", value=src_id), kind=EntityKind.CONCEPT, label=src_id
        ),
        candidate_entity=Entity(
            id=Identifier(namespace="EX", value=tgt_id), kind=EntityKind.CONCEPT, label=tgt_id
        ),
        composite_score=score,
        primary_method="label_similarity",
        score_breakdown={"label_similarity": score},
        evidence=[f"Similarity score {score}"],
    )


def test_confidence_threshold_routing_and_conservatism():
    config = DomainFusionConfig(
        confidence_thresholds=ConfidenceThresholds(
            high_confidence_threshold=0.88,
            review_threshold=0.65,
        )
    )
    decider = ConfidenceDecider(config)

    c_high = _make_candidate("High1", "High2", 0.95)
    c_med = _make_candidate("Med1", "Med2", 0.75)
    c_low = _make_candidate("Low1", "Low2", 0.50)

    result = decider.evaluate_candidates([c_high, c_med, c_low])

    # High -> Auto merged
    assert len(result.auto_merged_pairs) == 1
    assert result.auto_merged_pairs[0] == ("High1", "High2")

    # Medium -> Review required (NOT merged!)
    assert len(result.review_required_pairs) == 1
    assert result.review_required_pairs[0]["source_id"] == "Med1"

    # Low -> Kept separate
    assert len(result.kept_separate_pairs) == 1
    assert result.kept_separate_pairs[0]["source_id"] == "Low1"

    # Verify audit trail entries
    assert len(result.audit_entries) == 3
    audit_high = next(a for a in result.audit_entries if a.source_id == "High1")
    assert audit_high.decision == DecisionOutcome.MERGE_AUTOMATIC
    assert audit_high.action_taken == "AUTO_MERGE_CANONICAL"

    audit_med = next(a for a in result.audit_entries if a.source_id == "Med1")
    assert audit_med.decision == DecisionOutcome.REVIEW_REQUIRED
    assert audit_med.action_taken == "FLAGGED_FOR_HUMAN_REVIEW"
