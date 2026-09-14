"""Recall@K evaluation helpers for candidate resolution."""

from __future__ import annotations

from collections.abc import Sequence

from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch


def recall_at_k(ranked: Sequence[CandidateMatch], gold: Identifier, k: int) -> float:
    """Return 1.0 when the gold candidate is within the top ``k``, else 0.0."""
    if k < 1:
        raise ValueError("k must be at least 1")
    return float(any(match.candidate_entity.id == gold for match in ranked[:k]))


def mean_recall_at_k(
    cases: Sequence[tuple[Sequence[CandidateMatch], Identifier]],
    k: int,
) -> float:
    """Average Recall@K over ``cases`` of (ranked candidates, gold id)."""
    if not cases:
        return 0.0
    total = sum(recall_at_k(ranked, gold, k) for ranked, gold in cases)
    return total / len(cases)
