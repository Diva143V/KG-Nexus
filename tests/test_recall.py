from __future__ import annotations

import pytest

from core.entities.entity import Entity, EntityKind
from core.resolution.blocking import NormalizedLabelBlocking
from core.resolution.generator import PipelineCandidateGenerator
from core.resolution.models import CandidateMatch
from core.resolution.ranking import LexicalSimilarityRanker
from core.resolution.recall import mean_recall_at_k, recall_at_k
from core.resolution.retrieval import BlockedRetriever
from core.resolution.store import EntityStore
from tests.helpers import ident

ACTIVITY = ident("activity", "recall-1")
SOURCE = Entity(
    id=ident("entity", "s-1"),
    label="Alpha Beta",
    kind=EntityKind.CONCEPT,
)


def entity(entity_id: str, label: str) -> Entity:
    return Entity(id=ident("entity", entity_id), label=label, kind=EntityKind.CONCEPT)


def match(candidate: Entity, score: float) -> CandidateMatch:
    return CandidateMatch(
        source_entity=SOURCE,
        candidate_entity=candidate,
        ranking_score=score,
        ranking_method="lexical_similarity",
        activity_id=ACTIVITY,
    )


def test_recall_at_k_hits_within_k() -> None:
    gold = entity("e-1", "Alpha Beta")
    ranked = [match(gold, 1.0), match(entity("e-2", "Alpha"), 0.5)]
    assert recall_at_k(ranked, gold.id, 1) == 1.0


def test_recall_at_k_miss_beyond_k() -> None:
    gold = entity("e-3", "Gamma")
    ranked = [
        match(entity("e-1", "Alpha Beta"), 1.0),
        match(entity("e-2", "Alpha"), 0.5),
        match(gold, 0.25),
    ]
    assert recall_at_k(ranked, gold.id, 1) == 0.0
    assert recall_at_k(ranked, gold.id, 2) == 0.0
    assert recall_at_k(ranked, gold.id, 3) == 1.0


def test_recall_at_k_requires_positive_k() -> None:
    with pytest.raises(ValueError):
        recall_at_k([], ident("entity", "e-1"), 0)


def test_mean_recall_at_k_averages() -> None:
    gold = entity("e-1", "Alpha Beta")
    ranked = [match(gold, 1.0), match(entity("e-2", "Alpha"), 0.5)]
    cases = [(ranked, gold.id), (ranked, ident("entity", "missing"))]
    assert mean_recall_at_k(cases, 1) == 0.5
    assert mean_recall_at_k(cases, 2) == 0.5


def test_mean_recall_at_k_empty() -> None:
    assert mean_recall_at_k([], 5) == 0.0


def test_recall_demo_lexical_baseline() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    gold = entity("e-1", "Alpha Beta")
    store.register(gold)
    store.register(entity("e-2", "Alpha"))
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    ranked = generator.generate(source=SOURCE, activity_id=ACTIVITY)
    assert recall_at_k(ranked, gold.id, 1) == 1.0
