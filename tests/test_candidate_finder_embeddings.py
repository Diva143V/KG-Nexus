"""Integration tests for CandidateFinder with real embeddings enabled."""

from __future__ import annotations

import pytest

from core.entities.entity import Entity, EntityKind
from core.fusion.candidate_finder import (
    CandidateFinder,
    build_entity_surface_text,
)
from core.fusion.normalizer import NormalizedGraph
from core.identifiers.identifier import Identifier
from infrastructure.embeddings.protocol import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)
from sdk.domain_config import DomainFusionConfig, MatchStrategyConfig


class ControlledSemanticTestProvider(EmbeddingProvider):
    """Test double with controllable semantic distances."""

    def __init__(self, model_id: str = "test/controlled-semantic") -> None:
        self._model_id = model_id
        # Define high-similarity cluster for Metformin and Glucophage
        self.vectors = {
            "metformin": (1.0, 0.0, 0.0),
            "glucophage": (0.98, 0.1989, 0.0),  # cosine ~ 0.98
            "aspirin": (0.0, 1.0, 0.0),  # cosine ~ 0.0 with metformin
        }

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_type(self) -> str:
        return "test_double"

    @property
    def dimensions(self) -> int:
        return 3

    def is_available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        results = []
        for text in texts:
            t_lower = text.lower()
            matched = False
            for key, vec in self.vectors.items():
                if key in t_lower:
                    results.append(vec)
                    matched = True
                    break
            if not matched:
                results.append((0.0, 0.0, 1.0))
        return results

    def get_metadata(self) -> EmbeddingModelMetadata:
        return EmbeddingModelMetadata(
            model_id=self._model_id,
            provider_type="test_double",
            dimensions=3,
            model_digest="test_digest",
        )


def test_build_entity_surface_text():
    ent = Entity(
        id=Identifier(namespace="DRUG", value="d1"),
        kind=EntityKind.CONCEPT,
        label="Metformin",
    )
    graph = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="g1"),
        entities={"DRUG:d1": ent},
        literal_properties={
            ("DRUG:d1", "synonym"): ["Glucophage", "Metformin HCl"],
            ("DRUG:d1", "description"): ["Biguanide antihyperglycemic agent."],
        },
    )

    surface = build_entity_surface_text(ent, graph)
    assert "Metformin [concept]" in surface
    assert "Aliases: Glucophage, Metformin HCl" in surface
    assert "Description: Biguanide antihyperglycemic agent." in surface


def test_candidate_finder_without_embeddings():
    config = DomainFusionConfig(
        domain_id="test_dom",
        domain_name="Test",
        description="Test domain",
        match_strategy=MatchStrategyConfig(enable_embeddings=False),
    )
    finder = CandidateFinder(config)

    ent_a = Entity(
        id=Identifier(namespace="A", value="1"), kind=EntityKind.CONCEPT, label="Metformin"
    )
    ent_b = Entity(
        id=Identifier(namespace="B", value="2"), kind=EntityKind.CONCEPT, label="Glucophage"
    )

    graph_a = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="ga"),
        entities={"A:1": ent_a},
    )
    graph_b = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="gb"),
        entities={"B:2": ent_b},
    )

    candidates = finder.find_candidates(graph_a, graph_b, Identifier(namespace="ACT", value="act1"))
    # Different labels and no embeddings -> no match found
    assert len(candidates) == 0


def test_candidate_finder_with_real_embeddings_discovers_synonym():
    controlled_provider = ControlledSemanticTestProvider()
    config = DomainFusionConfig(
        domain_id="test_dom",
        domain_name="Test",
        description="Test domain",
        match_strategy=MatchStrategyConfig(
            enable_embeddings=True,
            embedding_provider="test_double",
            embedding_threshold=0.85,
            embedding_weight=0.5,
            exact_id_weight=0.5,
            label_similarity_weight=0.5,
        ),
    )
    finder = CandidateFinder(config, embedding_provider=controlled_provider)

    ent_a = Entity(
        id=Identifier(namespace="A", value="1"), kind=EntityKind.CONCEPT, label="Metformin"
    )
    ent_b = Entity(
        id=Identifier(namespace="B", value="2"), kind=EntityKind.CONCEPT, label="Glucophage"
    )

    graph_a = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="ga"),
        entities={"A:1": ent_a},
    )
    graph_b = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="gb"),
        entities={"B:2": ent_b},
    )

    candidates = finder.find_candidates(graph_a, graph_b, Identifier(namespace="ACT", value="act1"))

    # With semantic embeddings enabled, Metformin and Glucophage match with high cosine score!
    assert len(candidates) == 1
    match = candidates[0]
    assert match.source_entity.id.value == "1"
    assert match.candidate_entity.id.value == "2"
    assert "embedding_similarity" in match.score_breakdown
    assert match.score_breakdown["embedding_similarity"] >= 0.90
    assert match.primary_method == "semantic_embedding"

    # Evidence contains model and provider
    evidence_str = " ".join(match.evidence)
    assert "Embedding vector similarity" in evidence_str
    assert "model: test/controlled-semantic" in evidence_str
    assert "provider: test_double" in evidence_str


def test_candidate_finder_fail_closed_on_unavailable_provider():
    # Configure an unavailable provider
    config = DomainFusionConfig(
        domain_id="test_dom",
        domain_name="Test",
        description="Test domain",
        match_strategy=MatchStrategyConfig(
            enable_embeddings=True,
            embedding_provider="ollama",  # Ollama offline
        ),
    )
    finder = CandidateFinder(config)

    ent_a = Entity(
        id=Identifier(namespace="A", value="1"), kind=EntityKind.CONCEPT, label="EntityA"
    )
    ent_b = Entity(
        id=Identifier(namespace="B", value="2"), kind=EntityKind.CONCEPT, label="EntityB"
    )

    graph_a = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="ga"),
        entities={"A:1": ent_a},
    )
    graph_b = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="gb"),
        entities={"B:2": ent_b},
    )

    # Must raise explicit EmbeddingProviderUnavailableError rather than silently falling back
    with pytest.raises(EmbeddingProviderUnavailableError) as exc_info:
        finder.find_candidates(graph_a, graph_b, Identifier(namespace="ACT", value="act1"))
    assert "unavailable" in str(exc_info.value).lower()


class ZeroVectorProvider(EmbeddingProvider):
    """Returns all-zero vectors to test the zero-vector edge case."""

    @property
    def model_id(self) -> str:
        return "test/zero-vector"

    @property
    def provider_type(self) -> str:
        return "test_double"

    @property
    def dimensions(self) -> int:
        return 3

    def is_available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        # Return zero vectors for all inputs (e.g., empty or stop-word-only text)
        return [(0.0, 0.0, 0.0)] * len(texts)

    def get_metadata(self) -> EmbeddingModelMetadata:
        return EmbeddingModelMetadata(
            model_id=self.model_id,
            provider_type=self.provider_type,
            dimensions=3,
            model_digest="zero",
        )


def test_candidate_finder_zero_vector_does_not_crash():
    """Regression test: zero-vector embeddings must not crash or be silently skipped.

    A zero-vector tuple (0.0, 0.0, 0.0) is falsy in Python. The old `if vec_a and vec_b`
    guard would silently skip cosine scoring. With `is not None` the code correctly
    processes the zero vector (cos_sim=0.0) which falls below any threshold, so no
    match is emitted — but crucially no exception is raised.
    """
    provider = ZeroVectorProvider()
    config = DomainFusionConfig(
        domain_id="test_dom",
        domain_name="Test",
        description="Test domain",
        match_strategy=MatchStrategyConfig(
            enable_embeddings=True,
            embedding_provider="test_double",
            embedding_threshold=0.50,
            embedding_weight=1.0,
            exact_id_weight=0.0,
            label_similarity_weight=0.0,
        ),
    )
    finder = CandidateFinder(config, embedding_provider=provider)

    ent_a = Entity(
        id=Identifier(namespace="A", value="1"), kind=EntityKind.CONCEPT, label="EntityA"
    )
    ent_b = Entity(
        id=Identifier(namespace="B", value="2"), kind=EntityKind.CONCEPT, label="EntityB"
    )
    graph_a = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="ga"),
        entities={"A:1": ent_a},
    )
    graph_b = NormalizedGraph(
        graph_id=Identifier(namespace="G", value="gb"),
        entities={"B:2": ent_b},
    )

    # Must not raise; cos_sim(zero, zero) = 0.0 → below threshold → no candidates
    candidates = finder.find_candidates(graph_a, graph_b, Identifier(namespace="ACT", value="act1"))
    assert candidates == []  # 0.0 < 0.50 threshold, correctly not matched
