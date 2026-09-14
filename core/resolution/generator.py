"""Deterministic candidate generator composing retriever and ranker."""

from __future__ import annotations

from core.entities.entity import Entity
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch
from sdk.resolution import CandidateRanker, CandidateRetriever


class PipelineCandidateGenerator:
    """Retrieves and ranks candidates for a source entity.

    Never decides semantic identity: it only produces ranked candidates.
    """

    def __init__(
        self,
        *,
        retriever: CandidateRetriever,
        ranker: CandidateRanker,
    ) -> None:
        self._retriever = retriever
        self._ranker = ranker

    def generate(
        self,
        *,
        source: Entity,
        activity_id: Identifier,
    ) -> list[CandidateMatch]:
        candidates = self._retriever.retrieve(source=source, activity_id=activity_id)
        matches = [
            CandidateMatch(
                source_entity=source,
                candidate_entity=candidate,
                ranking_score=self._ranker.score(source, candidate),
                ranking_method=self._ranker.method,
                activity_id=activity_id,
            )
            for candidate in candidates
            if candidate.id != source.id
        ]
        matches.sort(
            key=lambda match: (
                -match.ranking_score,
                match.candidate_entity.id.canonical,
            )
        )
        return matches
