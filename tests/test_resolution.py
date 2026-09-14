from __future__ import annotations

import pytest

from core.entities.entity import Entity, EntityKind
from core.resolution.blocking import (
    ExactIdentifierBlocking,
    NormalizedLabelBlocking,
    normalized_label,
)
from core.resolution.generator import PipelineCandidateGenerator
from core.resolution.models import CandidateMatch
from core.resolution.policy import NullIdentityPolicy
from core.resolution.ranking import (
    ExactIdentifierRanker,
    LexicalSimilarityRanker,
    NormalizedLabelRanker,
    token_jaccard,
)
from core.resolution.retrieval import BlockedRetriever
from core.resolution.store import EntityStore
from tests.helpers import ident

ACTIVITY = ident("activity", "resolve-1")


def entity(entity_id: str, label: str) -> Entity:
    return Entity(id=ident("entity", entity_id), label=label, kind=EntityKind.CONCEPT)


def test_normalized_label_canonicalizes() -> None:
    assert normalized_label("  Some   Label  ") == "some label"
    assert normalized_label("Caf\u00e9") == "caf\u00e9"
    assert normalized_label("E\u0301mile") == "\u00e9mile"


def test_exact_identifier_blocking_key() -> None:
    blocking = ExactIdentifierBlocking()
    assert blocking.key(entity("e-1", "x")) == "entity:e-1"
    assert blocking.name == "exact_identifier"


def test_normalized_label_blocking_key() -> None:
    blocking = NormalizedLabelBlocking()
    assert blocking.key(entity("e-1", "  Some   Label ")) == "some label"
    assert blocking.name == "normalized_label"


def test_entity_store_register_and_retrieve() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    first = entity("e-1", "Alpha")
    second = entity("e-2", "  alpha  ")
    store.register(first)
    store.register(second)
    assert store.get(first.id) is first
    assert store.by_blocking_key("alpha") == (first, second)


def test_entity_store_rejects_duplicate_id() -> None:
    store = EntityStore(ExactIdentifierBlocking())
    store.register(entity("e-1", "Alpha"))
    with pytest.raises(ValueError):
        store.register(entity("e-1", "Beta"))


def test_blocked_retriever_exact_identifier() -> None:
    store = EntityStore(ExactIdentifierBlocking())
    candidate = entity("e-2", "Beta")
    store.register(candidate)
    retriever = BlockedRetriever(store)
    source = entity("e-2", "Beta")
    assert retriever.retrieve(source=source, activity_id=ACTIVITY) == [candidate]


def test_blocked_retriever_normalized_label() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    candidate = entity("e-2", "  Beta  ")
    store.register(candidate)
    retriever = BlockedRetriever(store)
    source = entity("e-9", "beta")
    assert retriever.retrieve(source=source, activity_id=ACTIVITY) == [candidate]


def test_exact_identifier_ranker() -> None:
    ranker = ExactIdentifierRanker()
    assert ranker.method == "exact_identifier"
    assert ranker.score(entity("e-1", "a"), entity("e-1", "b")) == 1.0
    assert ranker.score(entity("e-1", "a"), entity("e-2", "a")) == 0.0


def test_normalized_label_ranker() -> None:
    ranker = NormalizedLabelRanker()
    assert ranker.method == "normalized_label"
    assert ranker.score(entity("e-1", "  Alpha  "), entity("e-2", "alpha")) == 1.0
    assert ranker.score(entity("e-1", "Alpha"), entity("e-2", "Beta")) == 0.0


def test_lexical_similarity_ranker() -> None:
    ranker = LexicalSimilarityRanker()
    assert ranker.method == "lexical_similarity"
    assert ranker.score(entity("e-1", "Alpha Beta"), entity("e-2", "alpha beta")) == 1.0
    assert ranker.score(entity("e-1", "Alpha"), entity("e-2", "Gamma")) == 0.0
    partial = ranker.score(entity("e-1", "Alpha Beta"), entity("e-2", "Alpha Gamma"))
    assert 0.0 < partial < 1.0


def test_token_jaccard() -> None:
    assert token_jaccard("a b", "b a") == 1.0
    assert token_jaccard("a", "b") == 0.0
    assert token_jaccard("", "a") == 0.0


def test_generator_includes_required_fields() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    candidate = entity("e-2", "Beta")
    store.register(candidate)
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    source = entity("e-9", "Beta")
    matches = generator.generate(source=source, activity_id=ACTIVITY)
    assert len(matches) == 1
    match = matches[0]
    assert isinstance(match, CandidateMatch)
    assert match.source_entity == source
    assert match.candidate_entity == candidate
    assert match.ranking_score == 1.0
    assert match.ranking_method == "lexical_similarity"
    assert match.activity_id == ACTIVITY


def test_generator_excludes_source_entity() -> None:
    store = EntityStore(ExactIdentifierBlocking())
    store.register(entity("e-1", "Alpha"))
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=ExactIdentifierRanker(),
    )
    matches = generator.generate(source=entity("e-1", "Alpha"), activity_id=ACTIVITY)
    assert matches == []


def test_generator_orders_by_score_then_id() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    close = entity("b-2", "Alpha Beta")
    exact = entity("a-1", "Alpha Beta")
    store.register(close)
    store.register(exact)
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    source = entity("s-1", "Alpha Beta")
    matches = generator.generate(source=source, activity_id=ACTIVITY)
    assert [match.candidate_entity.id for match in matches] == [exact.id, close.id]
    assert matches[0].ranking_score >= matches[1].ranking_score


def test_generator_is_deterministic() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    for entity_id in ("c-3", "a-1", "b-2"):
        store.register(entity(entity_id, "Alpha Beta"))
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    source = entity("s-1", "Alpha Beta")
    first = generator.generate(source=source, activity_id=ACTIVITY)
    second = generator.generate(source=source, activity_id=ACTIVITY)
    assert first == second


def test_null_identity_policy_never_accepts() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    candidate = entity("e-2", "Beta")
    store.register(candidate)
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    source = entity("e-9", "Beta")
    match = generator.generate(source=source, activity_id=ACTIVITY)[0]
    decision = NullIdentityPolicy().decide(source=source, candidate=match)
    assert decision.accepted is False
    assert decision.method == "null"
    assert decision.source_entity == source
    assert decision.candidate_entity == candidate
    assert decision.activity_id == ACTIVITY


def test_candidate_match_is_immutable() -> None:
    store = EntityStore(NormalizedLabelBlocking())
    store.register(entity("e-2", "Beta"))
    generator = PipelineCandidateGenerator(
        retriever=BlockedRetriever(store),
        ranker=LexicalSimilarityRanker(),
    )
    match = generator.generate(source=entity("e-9", "Beta"), activity_id=ACTIVITY)[0]
    with pytest.raises((ValueError, TypeError)):
        match.ranking_score = 0.0
